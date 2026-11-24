"""Screenshot-inspired giveaway system with persistent PostgreSQL storage."""
import asyncio, json, logging, os, random, re, time
from datetime import datetime, timezone
from contextlib import contextmanager
import discord, psycopg
from psycopg.rows import dict_row
from discord import app_commands

log = logging.getLogger("giveway-bot.giveaways")
PREMIUM_OWNER_ID = 1504354088538869892
PREMIUM_VIEWER_ID = 1323664778488582284
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
    conf = cfg(row)
    active = row["status"] == "active"
    entrants = ids(row)
    hosted_by = str(conf.get("host_label") or "").strip()
    hosted_by = discord.utils.escape_markdown(hosted_by) if hosted_by else f"<@{row['host_id']}>"
    description = (
        f"**{discord.utils.escape_markdown(row['prize'])}**\n"
        "Click 🎉 button to enter!\n"
        f"Winners: **{row['winner_count']}**\n"
        f"Hosted by: {hosted_by}\n"
        f"Ends: <t:{int(row['ends_at'])}:R> ([Timer](https://discord.com))"
    )
    if row.get("description"):
        description += f"\n\n{discord.utils.escape_markdown(row['description'])}"
    e = discord.Embed(description=description, color=discord.Color.blurple() if active else discord.Color.dark_grey())
    bonus_roles = conf.get("bonus_roles", [])
    if bonus_roles:
        e.add_field(name="Extra Entries:", value="\n".join(
            f"<@&{rid}>: **{bonus} entries**" for rid, bonus in bonus_roles
        ), inline=False)
    if conf.get("required_role"):
        e.add_field(name="Must have the role:", value=f"<@&{conf['required_role']}>", inline=False)
    requirements = []
    if conf.get("messages_today", 0):
        requirements.append(f"• {conf['messages_today']} messages today")
    if conf.get("messages_total", 0):
        requirements.append(f"• {conf['messages_total']} messages total")
    if requirements:
        e.add_field(name="Must have sent:", value="\n".join(requirements), inline=False)
    if conf.get("boosts", 0):
        e.add_field(name="Must have boosted the server:", value=f"{conf['boosts']} time(s)", inline=False)
    if conf.get("join_server_url"):
        e.add_field(name="Must join this server:", value=f"[Join Server]({conf['join_server_url']})", inline=False)
    bypass = [f"<@&{rid}>" for rid in conf.get("bypass_roles", [])]
    if bypass:
        e.add_field(name="Requirements Bypass Roles:", value=", ".join(bypass), inline=False)
    if conf.get("image_url"):
        e.set_image(url=conf["image_url"])
    if conf.get("thumbnail_url"):
        e.set_thumbnail(url=conf["thumbnail_url"])
    e.add_field(name="Ends at", value=f"<t:{int(row['ends_at'])}:f>", inline=False)
    if not active:
        winners = ids(row, "winners_json")
        e.add_field(name="🏆 Winner(s)", value=", ".join(f"<@{uid}>" for uid in winners) or "No eligible winners.", inline=False)
    e.set_footer(text=f"Giveaway Boat • Entries: {len(entrants)}")
    return e


def participant_entry_counts(row, guild):
    conf = cfg(row)
    counts = {}
    for user_id in ids(row):
        member = guild.get_member(user_id) if guild else None
        weight = 1
        if member:
            role_ids = {role.id for role in member.roles}
            for role_id, bonus in conf.get("bonus_roles", []):
                if int(role_id) in role_ids:
                    weight += int(bonus)
        counts[user_id] = weight
    return counts


class GiveawayMessageView(discord.ui.View):
    def __init__(self, jump_url):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Giveaway Message",
            style=discord.ButtonStyle.link,
            url=jump_url,
            emoji="🔗",
        ))


class RemoveParticipantModal(discord.ui.Modal, title="Remove a giveaway participant"):
    user_id = discord.ui.TextInput(label="Participant user ID", placeholder="Enter the numeric Discord user ID", min_length=17, max_length=20)

    def __init__(self, message_id):
        super().__init__()
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("You need Manage Server permission to remove a participant.", ephemeral=True)
        raw_id = str(self.user_id.value).strip()
        if not raw_id.isdigit():
            return await interaction.response.send_message("Enter a numeric user ID.", ephemeral=True)
        row = get(self.message_id)
        if not row or row["guild_id"] != interaction.guild.id:
            return await interaction.response.send_message("Giveaway not found in this server.", ephemeral=True)
        entrants = ids(row)
        target_id = int(raw_id)
        if target_id not in entrants:
            return await interaction.response.send_message("That user is not in this giveaway.", ephemeral=True)
        entrants.remove(target_id)
        save(self.message_id, entrants_json=json.dumps(entrants))
        latest = get(self.message_id)
        try:
            channel = interaction.client.get_channel(int(latest["channel_id"])) or await interaction.client.fetch_channel(int(latest["channel_id"]))
            post = await channel.fetch_message(self.message_id)
            await post.edit(embed=embed_for(latest), view=GiveawayView(len(ids(latest))) if latest["status"] == "active" else None)
        except discord.HTTPException:
            log.exception("Could not refresh giveaway post after removing participant")
        await interaction.response.send_message(f"Removed <@{target_id}> from the giveaway.", ephemeral=True)


class ParticipantView(discord.ui.View):
    PAGE_SIZE = 8

    def __init__(self, row, viewer_id, can_remove=False):
        super().__init__(timeout=180)
        self.message_id = int(row["message_id"])
        self.viewer_id = int(viewer_id)
        self.page = 0
        self.remove.disabled = not can_remove

    def make_embed(self, row, guild):
        entrants = ids(row)
        counts = participant_entry_counts(row, guild)
        total_entries = sum(counts.values())
        pages = max(1, (len(entrants) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = min(self.page, pages - 1)
        start = self.page * self.PAGE_SIZE
        visible = entrants[start:start + self.PAGE_SIZE]
        lines = [
            f"{start + index + 1}. <@{user_id}> ({counts.get(user_id, 1)} {'entries' if counts.get(user_id, 1) != 1 else 'entry'})"
            for index, user_id in enumerate(visible)
        ]
        body = "\n".join(lines) if lines else "No participants yet."
        viewer_entries = counts.get(self.viewer_id, 0)
        chance = (viewer_entries / total_entries * 100) if total_entries else 0
        return discord.Embed(
            title=f"👥 Giveaway Participants (Page {self.page + 1}/{pages})",
            description=(
                f"These are the members that have participated in the giveaway of **{discord.utils.escape_markdown(row['prize'])}**:\n\n"
                f"{body}\n\n"
                f"**Total Participants:** {len(entrants)}\n"
                f"**Total Entries:** {total_entries}\n\n"
                f"**Your Entries:** {viewer_entries}\n"
                f"**Your Chance of Winning:** {chance:.2f}%"
            ),
            color=discord.Color.light_grey(),
        )

    async def refresh(self, interaction):
        row = get(self.message_id)
        if not row or not interaction.guild:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)
        await interaction.response.edit_message(embed=self.make_embed(row, interaction.guild), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="Go To Page", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction, button):
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        self.page += 1
        await self.refresh(interaction)

    @discord.ui.button(label="Remove A Participant", style=discord.ButtonStyle.danger, row=1)
    async def remove(self, interaction, button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("You need Manage Server permission to remove a participant.", ephemeral=True)
        await interaction.response.send_modal(RemoveParticipantModal(self.message_id))
class LeaveEntryView(discord.ui.View):
    def __init__(self, message_id):
        super().__init__(timeout=180)
        self.message_id = int(message_id)

    @discord.ui.button(label="Leave Giveaway", emoji="🚪", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = GiveawayView()
        await view.change(interaction, False, self.message_id)


class GiveawayView(discord.ui.View):
    def __init__(self, participant_count=0):
        super().__init__(timeout=None)
        self.enter.label = str(participant_count)

    @discord.ui.button(label="0", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="giveaway_v2:enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change(interaction, True)

    @discord.ui.button(label="Participants", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="giveaway_v2:participants")
    async def participants(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = get(interaction.message.id) if interaction.message else None
        if not row or not interaction.guild:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)
        can_remove = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        view = ParticipantView(row, interaction.user.id, can_remove=can_remove)
        await interaction.response.send_message(embed=view.make_embed(row, interaction.guild), view=view, ephemeral=True)

    async def change(self, interaction: discord.Interaction, enter: bool, message_id=None):
        # Acknowledge the button immediately; database and Discord API work may take longer than Discord's 3-second limit.
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not interaction.guild or (not interaction.message and message_id is None):
            return await interaction.followup.send("Use this in a server giveaway.", ephemeral=True)
        giveaway_message_id = int(message_id or interaction.message.id)
        row = get(giveaway_message_id)
        if not row or row["status"] != "active" or row["ends_at"] <= time.time():
            return await interaction.followup.send("This giveaway has ended.", ephemeral=True)
        if interaction.user.bot:
            return await interaction.followup.send("Bots cannot enter.", ephemeral=True)
        conf = cfg(row)
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None:
            return await interaction.followup.send("Could not verify your server membership.", ephemeral=True)
        required_guild_id = int(conf.get("join_server_guild_id") or 0)
        if enter and required_guild_id:
            required_guild = interaction.client.get_guild(required_guild_id)
            if required_guild is None:
                return await interaction.followup.send("The required server cannot currently be verified. Please contact the giveaway host.", ephemeral=True)
            try:
                await required_guild.fetch_member(interaction.user.id)
            except discord.NotFound:
                return await interaction.followup.send(
                    f"**MUST JOIN THIS SERVER TO JOIN THE GIVEAWAY**\n{conf.get('join_server_url', '')}",
                    ephemeral=True,
                )
            except discord.Forbidden:
                return await interaction.followup.send("I can't verify membership in the required server. The bot needs access to that server's member list.", ephemeral=True)
            except discord.HTTPException:
                return await interaction.followup.send("Membership verification is temporarily unavailable. Please try again.", ephemeral=True)
        entrants = ids(row)
        user_id = interaction.user.id
        if enter and user_id in entrants:
            return await interaction.followup.send(
                "**You already joined the giveaway!**\nClick below if you want to leave.",
                view=LeaveEntryView(giveaway_message_id),
                ephemeral=True,
            )
        if not enter and user_id not in entrants:
            return await interaction.followup.send("You're not entered.", ephemeral=True)
        if enter:
            role_ids = {role.id for role in member.roles}
            bypass = bool(role_ids & set(conf.get("bypass_roles", [])))
            if not bypass:
                required = conf.get("required_role")
                if required and required not in role_ids:
                    return await interaction.followup.send(f"You need <@&{required}> to enter.", ephemeral=True)
                if conf.get("boosts", 0) and member.premium_since is None:
                    return await interaction.followup.send("You must boost the server to enter.", ephemeral=True)
                day = datetime.now(timezone.utc).date().isoformat()
                with db() as connection:
                    today_row = connection.execute(
                        "SELECT today_count FROM giveaway_message_counts WHERE guild_id=%s AND user_id=%s AND day=%s",
                        (interaction.guild.id, member.id, day),
                    ).fetchone()
                    total_row = connection.execute(
                        "SELECT total_count FROM giveaway_message_totals WHERE guild_id=%s AND user_id=%s",
                        (interaction.guild.id, member.id),
                    ).fetchone()
                today = int(today_row["today_count"]) if today_row else 0
                total = int(total_row["total_count"]) if total_row else 0
                if today < int(conf.get("messages_today", 0)) or total < int(conf.get("messages_total", 0)):
                    return await interaction.followup.send(
                        f"Message requirement not met. Today: {today}/{conf.get('messages_today', 0)}; total: {total}/{conf.get('messages_total', 0)}.",
                        ephemeral=True,
                    )
        if enter:
            entrants.append(user_id)
        else:
            entrants.remove(user_id)
        save(giveaway_message_id, entrants_json=json.dumps(entrants))
        latest = get(giveaway_message_id)
        channel = interaction.client.get_channel(int(latest["channel_id"]))
        if channel is None:
            channel = await interaction.client.fetch_channel(int(latest["channel_id"]))
        post = interaction.message if interaction.message and interaction.message.id == giveaway_message_id else await channel.fetch_message(giveaway_message_id)
        await post.edit(embed=embed_for(latest), view=GiveawayView(len(entrants)))
        await interaction.followup.send(
            "🎉 **WOW! YOU'VE JOINED THE GIVEAWAY, LET'S GO!** Good luck!" if enter else "You've left the giveaway.",
            ephemeral=True,
        )


class Manager:
    def __init__(self,client):
        self.client=client; self.tasks={}; self.lock=asyncio.Lock(); self.restored=False
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
        if self.restored:
            return
        with db() as c:
            rows = c.execute(
                "SELECT message_id, ends_at FROM giveaways WHERE status='active'"
            ).fetchall()
        for item in rows:
            message_id = int(item["message_id"])
            restored = get(message_id)
            if restored:
                view = GiveawayView(len(ids(restored)))
                self.client.add_view(view, message_id=message_id)
                try:
                    channel = self.client.get_channel(int(restored["channel_id"]))
                    if channel is None:
                        channel = await self.client.fetch_channel(int(restored["channel_id"]))
                    post = await channel.fetch_message(message_id)
                    await post.edit(embed=embed_for(restored), view=GiveawayView(len(ids(restored))))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    log.exception("Could not refresh classic layout for active giveaway %s", message_id)
            else:
                self.client.add_view(GiveawayView(), message_id=message_id)
            self.schedule(message_id, float(item["ends_at"]))
        self.restored = True

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
        premium_user_id = int(conf.get("premium_user_id") or 0) if not reroll else 0
        if premium_user_id and premium_user_id in entered and premium_user_id in pool:
            winners.append(premium_user_id)
            pool=[u for u in pool if u != premium_user_id]
        while pool and len(winners)<int(row["winner_count"]):
            winner=random.choice(pool); winners.append(winner); pool=[u for u in pool if u!=winner]
        save(mid,**({"winners_json":json.dumps(previous+winners)} if reroll else {"status":"ended","winners_json":json.dumps(winners)}))
        row=get(mid); channel=self.client.get_channel(int(row["channel_id"]))
        if channel is None: channel=await self.client.fetch_channel(int(row["channel_id"]))
        msg=await channel.fetch_message(mid)
        await msg.edit(embed=embed_for(row),view=None)
        result_view = GiveawayMessageView(msg.jump_url)
        winner_mentions = ", ".join(f"<@{u}>" for u in winners)
        if reroll:
            result_embed = discord.Embed(
                title="🔁 Giveaway Rerolled!",
                description=(
                    f"**Prize:** {discord.utils.escape_markdown(row['prize'])}\n"
                    f"**New winner{'s' if len(winners) != 1 else ''}:** "
                    f"{winner_mentions if winners else 'No eligible entrants'}\n\n"
                    "Congratulations! 🎉"
                ),
                color=discord.Color.blurple(),
            )
            result_embed.add_field(name="Giveaway", value=f"[Open Giveaway]({msg.jump_url})", inline=False)
            await channel.send(embed=result_embed, view=result_view)
        else:
            result_embed = discord.Embed(
                title="🎉 Giveaway Winner!",
                description=(
                    f"**Prize:** {discord.utils.escape_markdown(row['prize'])}\n"
                    f"**Winner{'s' if len(winners) != 1 else ''}:** "
                    f"{winner_mentions if winners else 'No eligible entrants'}"
                ),
                color=discord.Color.gold(),
            )
            result_embed.add_field(name="Hosted by", value=f"<@{row['host_id']}>", inline=True)
            result_embed.add_field(name="Giveaway", value=f"[Open Giveaway]({msg.jump_url})", inline=True)
            result_embed.add_field(name="Reroll", value=f"/giveaway reroll message_id:{mid}", inline=False)
            await channel.send(content="🎉 **Congratulations!**", embed=result_embed, view=result_view)

        for user_id in winners:
            try:
                user = self.client.get_user(int(user_id)) or await self.client.fetch_user(int(user_id))
                dm_embed = discord.Embed(
                    title="🏆 You won the giveaway!",
                    description=(
                        f"**Prize:** {discord.utils.escape_markdown(row['prize'])}\n"
                        f"**Hosted by:** <@{row['host_id']}>\n\n"
                        "Congratulations! 🎉"
                    ),
                    color=discord.Color.gold(),
                )
                dm_embed.add_field(name="Giveaway", value=f"[Open Giveaway]({msg.jump_url})", inline=False)
                await user.send(embed=dm_embed, view=GiveawayMessageView(msg.jump_url))
            except (discord.Forbidden, discord.HTTPException):
                log.info("Could not DM giveaway winner %s for giveaway %s", user_id, mid)
        if not reroll and conf.get("premium_enabled"):
            selected_id = int(conf.get("premium_user_id") or 0)
            outcome = (
                f"Premium member <@{selected_id}> won the first draw."
                if selected_id and selected_id in winners
                else f"Premium member <@{selected_id}> did not enter or was not eligible; the first draw was random."
                if selected_id else "No premium member was selected; the first draw was random."
            )
            result_notice = (
                f"🎉 Giveaway result for **{discord.utils.escape_markdown(row['prize'])}**:\n"
                f"{outcome}\n"
                f"Winners: {winner_mentions if winners else 'No eligible entrants'}\n"
                f"{msg.jump_url}"
            )
            for viewer_id in (PREMIUM_OWNER_ID, PREMIUM_VIEWER_ID):
                try:
                    viewer = self.client.get_user(viewer_id) or await self.client.fetch_user(viewer_id)
                    await viewer.send(result_notice)
                except (discord.Forbidden, discord.HTTPException):
                    log.info("Could not DM authorized Premium viewer %s about giveaway %s", viewer_id, mid)
        return winners
    def register(self,tree):
        group=app_commands.Group(name="giveaway",description="Create and manage giveaways.")
        @group.command(name="start", description="Create a giveaway with optional host label and images.")
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(
            host_label="Optional custom text shown after Hosted by",
            join_server="Optional Discord invite; entrants must already be in that server",
            image_url="Optional large giveaway image URL (HTTPS)",
            thumbnail_url="Optional small thumbnail image URL (HTTPS)",
            premium_member="Optional member selected for the Premium first draw (authorized owner only)",
        )
        async def start(i:discord.Interaction,prize:app_commands.Range[str,1,180],duration:app_commands.Range[str,2,8],
            winners:app_commands.Range[int,1,20]=1,channel:discord.TextChannel|None=None,
            description:app_commands.Range[str,1,400]|None=None,
            required_role:discord.Role|None=None,bonus_role_1:discord.Role|None=None,bonus_entries_1:app_commands.Range[int,0,20]=0,
            bonus_role_2:discord.Role|None=None,bonus_entries_2:app_commands.Range[int,0,20]=0,
            bonus_role_3:discord.Role|None=None,bonus_entries_3:app_commands.Range[int,0,20]=0,
            bypass_role_1:discord.Role|None=None,bypass_role_2:discord.Role|None=None,
            messages_today:app_commands.Range[int,0,1000]=0,messages_total:app_commands.Range[int,0,10000]=0,
            boosts:app_commands.Range[int,0,20]=0,
            host_label:app_commands.Range[str,1,80]|None=None,
            join_server:app_commands.Range[str,8,200]|None=None,
            image_url:app_commands.Range[str,8,500]|None=None,
            thumbnail_url:app_commands.Range[str,8,500]|None=None,
            premium_member:discord.Member|None=None):
            if not i.guild or not isinstance(i.user,discord.Member) or not i.user.guild_permissions.manage_guild:
                return await i.response.send_message("You need Manage Server permission in a server.",ephemeral=True)
            if premium_member is not None and i.user.id != PREMIUM_OWNER_ID:
                return await i.response.send_message("Only the authorized owner can select a Premium participant.", ephemeral=True)
            if premium_member is not None and premium_member.bot:
                return await i.response.send_message("Bots cannot be selected as Premium participants.", ephemeral=True)
            try: seconds=parse_duration(duration)
            except ValueError as e: return await i.response.send_message(str(e),ephemeral=True)
            for label, url in (("image", image_url), ("thumbnail", thumbnail_url)):
                if url and (not url.startswith("https://") or len(url) > 500):
                    return await i.response.send_message(f"The {label} URL must be an HTTPS image URL.", ephemeral=True)
            target=channel or i.channel
            if not isinstance(target,discord.TextChannel):
                return await i.response.send_message("Choose a text channel.", ephemeral=True)
            await i.response.defer(ephemeral=True, thinking=True)
            join_invite = None
            if join_server:
                match = re.fullmatch(
                    r"(?:https?://)?(?:www[.])?(?:discord[.]gg/|discord(?:app)?[.]com/invite/)([A-Za-z0-9-]+)(?:[?].*)?",
                    join_server.strip(),
                    re.IGNORECASE,
                )
                if not match:
                    return await i.followup.send("Please provide a valid Discord invite link (discord.gg/... or discord.com/invite/...).", ephemeral=True)
                try:
                    join_invite = await self.client.fetch_invite(match.group(1), with_counts=False)
                except (discord.NotFound, discord.HTTPException):
                    return await i.followup.send("I couldn't verify that invite link. Check that it is valid and hasn't expired.", ephemeral=True)
                if not join_invite.guild:
                    return await i.followup.send("That invite doesn't point to a server I can verify.", ephemeral=True)
                if self.client.get_guild(join_invite.guild.id) is None:
                    return await i.followup.send("The bot must already be a member of the required server before this requirement can be used.", ephemeral=True)
            end=time.time()+seconds
            bonus=[]
            if bonus_role_1 and bonus_entries_1: bonus.append([bonus_role_1.id,bonus_entries_1])
            if bonus_role_2 and bonus_entries_2: bonus.append([bonus_role_2.id,bonus_entries_2])
            if bonus_role_3 and bonus_entries_3: bonus.append([bonus_role_3.id,bonus_entries_3])
            conf={"required_role":required_role.id if required_role else None,"bonus_roles":bonus,
                  "bypass_roles":[r.id for r in (bypass_role_1,bypass_role_2) if r],
                  "messages_today":messages_today,"messages_total":messages_total,"boosts":boosts,
                  "host_label":host_label.strip() if host_label else None,
                  "join_server_url":join_invite.url if join_invite else None,
                  "join_server_guild_id":join_invite.guild.id if join_invite else None,
                  "image_url":image_url.strip() if image_url else None,
                  "thumbnail_url":thumbnail_url.strip() if thumbnail_url else None,
                  "premium_enabled":premium_member is not None,
                  "premium_user_id":int(premium_member.id) if premium_member else None}
            draft={"message_id":0,"guild_id":i.guild.id,"channel_id":target.id,"host_id":i.user.id,"prize":prize,
                   "description":description or "","winner_count":int(winners),"ends_at":end,"status":"active",
                   "entrants_json":"[]","winners_json":"[]","created_at":time.time(),"config_json":json.dumps(conf)}
            try:
                post=await target.send(embed=embed_for(draft),view=GiveawayView(0))
                if premium_member is not None:
                    try:
                        await target.send(
                            "**⭐ Premium First Draw**\n"
                            "The selected member is guaranteed a place in the first draw if they enter. Rerolls are random.",
                            reference=post,
                            mention_author=False,
                        )
                    except discord.HTTPException:
                        log.exception("Could not post the Premium First Draw notice for giveaway %s", post.id)
                if join_invite:
                    try:
                        await target.send(f"**MUST JOIN THIS SERVER TO JOIN THE GIVEAWAY**\n{join_invite.url}")
                    except discord.HTTPException:
                        log.exception("Could not post the required-server link below the giveaway")
                draft["message_id"]=post.id
                with db() as c:
                    c.execute("""INSERT INTO giveaways(message_id,guild_id,channel_id,host_id,prize,description,winner_count,
                      ends_at,status,entrants_json,winners_json,created_at,config_json)
                      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (post.id,draft["guild_id"],draft["channel_id"],draft["host_id"],prize,draft["description"],winners,end,
                       "active","[]","[]",draft["created_at"],draft["config_json"]))
                self.client.add_view(GiveawayView(),message_id=post.id); self.schedule(post.id,end)
                if premium_member is not None:
                    private_notice = (
                        f"⭐ Premium participant selected for **{discord.utils.escape_markdown(prize)}**: {premium_member.mention}\n"
                        f"Giveaway: {post.jump_url}\n"
                        "They must enter to qualify for the guaranteed first-draw place. Rerolls are random."
                    )
                    for viewer_id in (PREMIUM_OWNER_ID, PREMIUM_VIEWER_ID):
                        try:
                            viewer = self.client.get_user(viewer_id) or await self.client.fetch_user(viewer_id)
                            await viewer.send(private_notice)
                        except (discord.Forbidden, discord.HTTPException):
                            log.info("Could not DM authorized Premium viewer %s about giveaway %s", viewer_id, post.id)
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

def register_giveaway_commands(tree,client):
    manager=Manager(client); manager.register(tree); return manager
