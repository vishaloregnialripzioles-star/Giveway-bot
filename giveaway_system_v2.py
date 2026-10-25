"""Screenshot-inspired giveaway system with persistent PostgreSQL storage."""
import asyncio, json, logging, os, random, re, time
from datetime import datetime, timezone
from contextlib import contextmanager
import discord, psycopg
from psycopg.rows import dict_row
from discord import app_commands

log = logging.getLogger("giveway-bot.giveaways")
DB_URL = os.getenv("DATABASE_URL", "").strip()
if not DB_URL:
    raise RuntimeError("DATABASE_URL is missing. Configure the Supabase Session Pooler URI in Render.")

def db_connect():
    return psycopg.connect(DB_URL, sslmode="require", connect_timeout=10, row_factory=dict_row)

def init_db():
    with db_connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS giveaways (
          message_id BIGINT PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL,
          host_id BIGINT NOT NULL, prize TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
          winner_count INTEGER NOT NULL, ends_at DOUBLE PRECISION NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          entrants_json TEXT NOT NULL DEFAULT '[]', winners_json TEXT NOT NULL DEFAULT '[]',
          created_at DOUBLE PRECISION NOT NULL, config_json TEXT NOT NULL DEFAULT '{}')""")
        c.execute("ALTER TABLE giveaways ADD COLUMN IF NOT EXISTS config_json TEXT NOT NULL DEFAULT '{}'")
        c.execute("""CREATE TABLE IF NOT EXISTS giveaway_message_counts (
          guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, day TEXT NOT NULL,
          today_count INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (guild_id, user_id, day))""")
        c.execute("""CREATE TABLE IF NOT EXISTS giveaway_message_totals (
          guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, total_count BIGINT NOT NULL DEFAULT 0,
          PRIMARY KEY (guild_id, user_id))""")
init_db()

@contextmanager
def db():
    c=db_connect()
    try:
        yield c
        c.commit()
    finally: c.close()

def get(mid):
    with db() as c:
        r=c.execute("SELECT * FROM giveaways WHERE message_id=%s",(mid,)).fetchone()
        return dict(r) if r else None

def save(mid, **fields):
    allowed={"status","entrants_json","winners_json","config_json"}
    if not fields or not set(fields)<=allowed: raise ValueError("Invalid giveaway update")
    with db() as c:
        c.execute("UPDATE giveaways SET "+", ".join(f"{k}=%s" for k in fields)+" WHERE message_id=%s",(*fields.values(),mid))

def ids(row,key="entrants_json"):
    try: return [int(x) for x in json.loads(row[key])]
    except (ValueError,TypeError,json.JSONDecodeError): return []

def cfg(row):
    try: return json.loads(row.get("config_json") or "{}")
    except (TypeError,json.JSONDecodeError): return {}

def parse_duration(s):
    m=re.fullmatch(r"(\d{1,5})(s|m|h|d)",s.strip(),re.I)
    if not m: raise ValueError("Use 30s, 10m, 2h, or 1d.")
    n=int(m.group(1))*{"s":1,"m":60,"h":3600,"d":86400}[m.group(2).lower()]
    if not 30<=n<=2592000: raise ValueError("Duration must be 30 seconds to 30 days.")
    return n

def embed_for(row):
    conf=cfg(row); active=row["status"]=="active"; entrants=ids(row)
    e=discord.Embed(description=f"**{discord.utils.escape_markdown(row['prize'])}**\n\nClick 🎉 button to enter!\nWinners: **{row['winner_count']}**\nHosted by: <@{row['host_id']}>\nEnds: <t:{int(row['ends_at'])}:R> ([Timer](https://discord.com))",
      color=discord.Color.blurple() if active else discord.Color.dark_grey())
    e.add_field(name="Extra Entries:",value="\n".join(f"<@&{rid}>: **{bonus} entries**" for rid,bonus in conf.get("bonus_roles",[])) or "None",inline=False)
    e.add_field(name="Must have the role:",value=f"<@&{conf['required_role']}>" if conf.get("required_role") else "None",inline=False)
    e.add_field(name="Must have sent:",value=f"• {conf.get('messages_today',0)} message(s) today\n• {conf.get('messages_total',0)} messages total",inline=False)
    e.add_field(name="Must have boosted the server",value=f"{conf.get('boosts',0)} time(s)",inline=False)
    bypass=[f"<@&{r}>" for r in conf.get("bypass_roles",[])]
    e.add_field(name="Requirements Bypass Roles:",value=", ".join(bypass) or "None",inline=False)
    e.add_field(name="Ends at",value=f"<t:{int(row['ends_at'])}:f>",inline=False)
    if not active:
        winners=ids(row,"winners_json")
        e.add_field(name="🏆 Winner(s)",value=", ".join(f"<@{u}>" for u in winners) or "No eligible winners.",inline=False)
    e.set_footer(text=f"Giveaway Boat • Entries: {len(entrants)}")
    return e

class ParticipantView(discord.ui.View):
    def __init__(self, row):
        super().__init__(timeout=120)
        self.row=row
    @discord.ui.button(label="Refresh participants",emoji="👥",style=discord.ButtonStyle.secondary)
    async def refresh(self,i,b):
        row=get(self.row["message_id"])
        if not row: return await i.response.send_message("Giveaway not found.",ephemeral=True)
        entrants=ids(row)
        body=", ".join(f"<@{u}>" for u in entrants[:80]) or "No participants yet."
        if len(entrants)>80: body+=f"\n…and {len(entrants)-80} more."
        await i.response.send_message(f"**Participants ({len(entrants)})**\n{body}",ephemeral=True)

class GiveawayView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎉",style=discord.ButtonStyle.primary,custom_id="giveaway_v2:enter")
    async def enter(self,i,b): await self.change(i,True)
    @discord.ui.button(label="Participants",emoji="👥",style=discord.ButtonStyle.secondary,custom_id="giveaway_v2:participants")
    async def participants(self,i,b):
        row=get(i.message.id) if i.message else None
        if not row: return await i.response.send_message("Giveaway not found.",ephemeral=True)
        entrants=ids(row)
        body=", ".join(f"<@{u}>" for u in entrants[:80]) or "No participants yet."
        if len(entrants)>80: body+=f"\n…and {len(entrants)-80} more."
        await i.response.send_message(f"**Participants ({len(entrants)})**\n{body}",ephemeral=True)
    async def change(self,i,enter):
        if not i.guild or not i.message: return await i.response.send_message("Use this in a server giveaway.",ephemeral=True)
        row=get(i.message.id)
        if not row or row["status"]!="active" or row["ends_at"]<=time.time():
            return await i.response.send_message("This giveaway has ended.",ephemeral=True)
        if i.user.bot: return await i.response.send_message("Bots cannot enter.",ephemeral=True)
        conf=cfg(row); member=i.user if isinstance(i.user,discord.Member) else None
        if member is None: return await i.response.send_message("Could not verify your server membership.",ephemeral=True)
        role_ids={r.id for r in member.roles}; bypass=bool(role_ids & set(conf.get("bypass_roles",[])))
        if not bypass:
            required=conf.get("required_role")
            if required and required not in role_ids: return await i.response.send_message(f"You need <@&{required}> to enter.",ephemeral=True)
            if conf.get("boosts",0) and member.premium_since is None: return await i.response.send_message("You must boost the server to enter.",ephemeral=True)
            day=datetime.now(timezone.utc).date().isoformat()
            with db() as c:
                count=c.execute("SELECT today_count FROM giveaway_message_counts WHERE guild_id=%s AND user_id=%s AND day=%s",(i.guild.id,member.id,day)).fetchone()
                total_row=c.execute("SELECT total_count FROM giveaway_message_totals WHERE guild_id=%s AND user_id=%s",(i.guild.id,member.id)).fetchone()
            today=int(count["today_count"]) if count else 0
            total=int(total_row["total_count"]) if total_row else 0
            if today<int(conf.get("messages_today",0)) or total<int(conf.get("messages_total",0)):
                return await i.response.send_message(f"Message requirement not met. Today: {today}/{conf.get('messages_today',0)}; total: {total}/{conf.get('messages_total',0)}.",ephemeral=True)
        entrants=ids(row); uid=i.user.id
        if enter and uid in entrants: return await i.response.send_message("You're already entered! 🍀",ephemeral=True)
        if not enter and uid not in entrants: return await i.response.send_message("You're not entered.",ephemeral=True)
        if enter: entrants.append(uid)
        else: entrants.remove(uid)
        save(row["message_id"],entrants_json=json.dumps(entrants))
        await i.message.edit(embed=embed_for(get(row["message_id"])),view=self)
        await i.response.send_message("🎉 You're entered! Good luck!" if enter else "You've left the giveaway.",ephemeral=True)

class Manager:
    def __init__(self,client):
        self.client=client; self.tasks={}; self.lock=asyncio.Lock(); self.restored=False
        client.add_listener(self.on_message,"on_message")
    async def on_message(self,message):
        if not message.guild or message.author.bot: return
        day=datetime.now(timezone.utc).date().isoformat()
        with db() as c:
            c.execute("""INSERT INTO giveaway_message_counts(guild_id,user_id,day,today_count)
              VALUES(%s,%s,%s,1) ON CONFLICT(guild_id,user_id,day)
              DO UPDATE SET today_count=giveaway_message_counts.today_count+1""",
              (message.guild.id,message.author.id,day))
            c.execute("""INSERT INTO giveaway_message_totals(guild_id,user_id,total_count)
              VALUES(%s,%s,1) ON CONFLICT(guild_id,user_id)
              DO UPDATE SET total_count=giveaway_message_totals.total_count+1""",
              (message.guild.id,message.author.id))
    async def restore_views(self):
        if self.restored:return
        with db() as c: rows=c.execute("SELECT message_id,ends_at FROM giveaways WHERE status='active'").fetchall()
        for r in rows:
            self.client.add_view(GiveawayView(),message_id=int(r["message_id"]))
            self.schedule(int(r["message_id"]),float(r["ends_at"]))
        self.restored=True
    def schedule(self,mid,end):
        if mid in self.tasks and not self.tasks[mid].done(): return
        self.tasks[mid]=asyncio.create_task(self.end_later(mid,end))
    async def end_later(self,mid,end):
        await asyncio.sleep(max(0,end-time.time()))
        try: await self.finish(mid)
        except Exception: log.exception("Failed to finish giveaway %s",mid)
    async def finish(self,mid,reroll=False):
        row=get(mid)
        if not row: raise ValueError("Giveaway not found.")
        if not reroll and row["status"]!="active": raise ValueError("Giveaway already ended or cancelled.")
        conf=cfg(row); entered=ids(row); weights=[]
        guild=self.client.get_guild(int(row["guild_id"]))
        for uid in entered:
            member=guild.get_member(uid) if guild else None
            weight=1
            if member:
                roles={r.id for r in member.roles}
                if not (roles & set(conf.get("bypass_roles",[]))):
                    if conf.get("required_role") and conf["required_role"] not in roles: continue
                    if conf.get("boosts",0) and member.premium_since is None: continue
                for rid,bonus in conf.get("bonus_roles",[]):
                    if member and int(rid) in {r.id for r in member.roles}: weight+=int(bonus)
            weights.extend([uid]*max(1,weight))
        previous=ids(row,"winners_json") if reroll else []
        pool=[u for u in weights if u not in previous]; winners=[]
        while pool and len(winners)<int(row["winner_count"]):
            winner=random.choice(pool); winners.append(winner); pool=[u for u in pool if u!=winner]
        save(mid,**({"winners_json":json.dumps(previous+winners)} if reroll else {"status":"ended","winners_json":json.dumps(winners)}))
        row=get(mid); channel=self.client.get_channel(int(row["channel_id"]))
        if channel is None: channel=await self.client.fetch_channel(int(row["channel_id"]))
        msg=await channel.fetch_message(mid)
        await msg.edit(embed=embed_for(row),view=None)
        await channel.send("🎊 Congratulations "+(", ".join(f"<@{u}>" for u in winners) if winners else "No eligible entrants")+"! Giveaway result for **"+row["prize"]+"**.")
        return winners
    def register(self,tree):
        group=app_commands.Group(name="giveaway",description="Create and manage giveaways.")
        @group.command(name="start",description="Create a screenshot-style giveaway post.")
        @app_commands.default_permissions(manage_guild=True)
        async def start(i:discord.Interaction,prize:app_commands.Range[str,1,180],duration:app_commands.Range[str,2,8],
            winners:app_commands.Range[int,1,20]=1,channel:discord.TextChannel|None=None,
            description:app_commands.Range[str,1,400]|None=None,
            required_role:discord.Role|None=None,bonus_role_1:discord.Role|None=None,bonus_entries_1:app_commands.Range[int,1,20]=0,
            bonus_role_2:discord.Role|None=None,bonus_entries_2:app_commands.Range[int,1,20]=0,
            bypass_role_1:discord.Role|None=None,bypass_role_2:discord.Role|None=None,
            messages_today:app_commands.Range[int,0,1000]=0,messages_total:app_commands.Range[int,0,10000]=0,
            boosts:app_commands.Range[int,0,20]=0):
            if not i.guild or not isinstance(i.user,discord.Member) or not i.user.guild_permissions.manage_guild:
                return await i.response.send_message("You need Manage Server permission in a server.",ephemeral=True)
            try: seconds=parse_duration(duration)
            except ValueError as e: return await i.response.send_message(str(e),ephemeral=True)
            target=channel or i.channel
            if not isinstance(target,discord.TextChannel): return await i.response.send_message("Choose a text channel.",ephemeral=True)
            await i.response.defer(ephemeral=True,thinking=True)
            end=time.time()+seconds
            bonus=[]
            if bonus_role_1 and bonus_entries_1: bonus.append([bonus_role_1.id,bonus_entries_1])
            if bonus_role_2 and bonus_entries_2: bonus.append([bonus_role_2.id,bonus_entries_2])
            conf={"required_role":required_role.id if required_role else None,"bonus_roles":bonus,
                  "bypass_roles":[r.id for r in (bypass_role_1,bypass_role_2) if r],
                  "messages_today":messages_today,"messages_total":messages_total,"boosts":boosts}
            draft={"message_id":0,"guild_id":i.guild.id,"channel_id":target.id,"host_id":i.user.id,"prize":prize,
                   "description":description or "","winner_count":int(winners),"ends_at":end,"status":"active",
                   "entrants_json":"[]","winners_json":"[]","created_at":time.time(),"config_json":json.dumps(conf)}
            try:
                post=await target.send(embed=embed_for(draft),view=GiveawayView())
                draft["message_id"]=post.id
                with db() as c:
                    c.execute("""INSERT INTO giveaways(message_id,guild_id,channel_id,host_id,prize,description,winner_count,
                      ends_at,status,entrants_json,winners_json,created_at,config_json)
                      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (post.id,draft["guild_id"],draft["channel_id"],draft["host_id"],prize,draft["description"],winners,end,
                       "active","[]","[]",draft["created_at"],draft["config_json"]))
                self.client.add_view(GiveawayView(),message_id=post.id); self.schedule(post.id,end)
                await i.followup.send(f"Giveaway posted in {target.mention}: {post.jump_url}",ephemeral=True)
            except Exception:
                log.exception("Giveaway creation failed")
                await i.followup.send("Could not create giveaway. Check bot permissions and Render logs.",ephemeral=True)
        async def manage(i,mid,mode):
            if not i.guild or not isinstance(i.user,discord.Member) or not i.user.guild_permissions.manage_guild:
                return await i.response.send_message("You need Manage Server permission.",ephemeral=True)
            if not str(mid).isdigit(): return await i.response.send_message("Enter a numeric giveaway message ID.",ephemeral=True)
            row=get(int(mid))
            if not row or row["guild_id"]!=i.guild.id: return await i.response.send_message("Giveaway not found in this server.",ephemeral=True)
            try:
                await i.response.defer(ephemeral=True,thinking=True)
                if mode=="cancel":
                    if row["status"]!="active": raise ValueError("Giveaway is not active.")
                    save(int(mid),status="cancelled"); row=get(int(mid))
                    ch=self.client.get_channel(int(row["channel_id"])) or await self.client.fetch_channel(int(row["channel_id"]))
                    msg=await ch.fetch_message(int(mid)); await msg.edit(embed=embed_for(row),view=None)
                    await i.followup.send("Giveaway cancelled.",ephemeral=True)
                else:
                    wins=await self.finish(int(mid),reroll=mode=="reroll")
                    await i.followup.send("Winners: "+(", ".join(f"<@{u}>" for u in wins) if wins else "No eligible entrants."),ephemeral=True)
            except ValueError as e: await i.followup.send(str(e),ephemeral=True)
        @group.command(name="end",description="End an active giveaway now.")
        async def end(i:discord.Interaction,message_id:str): await manage(i,message_id,"end")
        @group.command(name="reroll",description="Reroll winners from remaining entrants.")
        async def reroll(i:discord.Interaction,message_id:str): await manage(i,message_id,"reroll")
        @group.command(name="cancel",description="Cancel without choosing winners.")
        async def cancel(i:discord.Interaction,message_id:str): await manage(i,message_id,"cancel")
        @group.command(name="entrants",description="View giveaway participants.")
        async def entrants(i:discord.Interaction,message_id:str):
            if not str(message_id).isdigit(): return await i.response.send_message("Enter a numeric message ID.",ephemeral=True)
            row=get(int(message_id))
            if not row or row["guild_id"]!=i.guild_id: return await i.response.send_message("Giveaway not found.",ephemeral=True)
            users=ids(row); body=", ".join(f"<@{u}>" for u in users[:80]) or "No entrants."
            if len(users)>80: body+=f" and {len(users)-80} more"
            await i.response.send_message(f"Participants ({len(users)}): {body}",ephemeral=True)
        tree.add_command(group)
    return self

def register_giveaway_commands(tree,client):
    manager=Manager(client); manager.register(tree); return manager
