import random
import asyncio
import db
import hashlib
import discord
from discord import app_commands

def embed(title, desc="", color=None):
    return discord.Embed(title=f"✈️ {title}", description=desc, color=color or discord.Color.blurple(), timestamp=discord.utils.utcnow())

def seed(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)

def setup(bot):
    class LobbyView(discord.ui.View):
        def __init__(self, game, session_id):
            super().__init__(timeout=31); self.game=game; self.session_id=session_id; self.message=None; self.remaining=30
        async def on_timeout(self):
            info=await db.session_info(self.session_id)
            if not info or info["status"] != "lobby": return
            await db.close_session(self.session_id, "cancelled")
            if self.message:
                try: await self.message.edit(embed=embed(f"{self.game.title()} • Lobby Closed ⏰","No players joined before the 30-second countdown ended. Game cancelled.",discord.Color.red()),view=None)
                except discord.HTTPException: pass
        @discord.ui.button(label="Join Game",emoji="🎮",style=discord.ButtonStyle.success)
        async def join(self,interaction,button):
            ok=await db.join_session(self.session_id,interaction.user.id)
            if not ok: return await interaction.response.send_message("❌ Lobby is closed.",ephemeral=True)
            await interaction.response.send_message(f"✅ {interaction.user.mention} joined **{self.game.title()}**! Watch the lobby countdown.",ephemeral=True)
        @discord.ui.button(label="How to Play",emoji="📖",style=discord.ButtonStyle.primary)
        async def how(self,interaction,button):
            e=embed(f"How to Play • {self.game.title()}","**1. Join** the lobby before the timer ends.\n**2. Wait** for the 30-second countdown.\n**3. Start:** the bot creates the scenario automatically.\n**4. Play:** use the action buttons/turn commands to make decisions.\n**5. Progress:** earn virtual coins, XP, loot and achievements.\n\n💾 Everything is saved to PostgreSQL.\n\n⚠️ If **0 players** have joined when the timer ends, the lobby is cancelled automatically.",discord.Color.green())
            await interaction.response.send_message(embed=e,ephemeral=True)

    async def lobby_countdown(message,game,sid,view):
        view.message=message
        for remaining in range(30,0,-1):
            view.remaining=remaining
            try:
                rows=await db.session_players(sid)
                e=embed(f"{game.title()} • Lobby 🎮",f"**Session:** #{sid}\n\n📖 **How to play**\nJoin with **🎮 Join Game**. The game starts automatically after 30 seconds. During the game, follow the action buttons and turn prompts. Your rewards and progress are saved.\n\n👥 **Players:** {len(rows)}\n⏱️ **Starting in: {remaining}s**",discord.Color.blurple())
                e.set_footer(text="No players joined by the end = lobby automatically cancelled.")
                await message.edit(embed=e,view=view)
            except discord.HTTPException: return
            await asyncio.sleep(1)
        rows=await db.session_players(sid)
        if not rows:
            await db.close_session(sid,"cancelled")
            try: await message.edit(embed=embed(f"{game.title()} • Cancelled ⏰","The 30-second lobby ended with **0 players**. Nothing was charged or changed.",discord.Color.red()),view=None)
            except discord.HTTPException: pass
            return
        await db.close_session(sid,"active")
        try: await message.edit(embed=embed(f"{game.title()} • GAME STARTED 🚀",f"**{len(rows)} player(s)** joined! The game is now starting.\n\n🎯 Make decisions when the bot presents each turn.\n💾 XP, coins and progression are saved.",discord.Color.green()),view=None)
        except discord.HTTPException: pass

    @bot.tree.command(name="startgame", description="Start a persistent multiplayer game")
    @app_commands.describe(game="Game name")
    async def startgame(i, game: str):
        allowed={"heist","kingdom","assassin","blackmarket","escape","outbreak","conquest","treasure","arena","casino","detective","zombie","race","pirate","dungeon"}
        game=game.lower().strip()
        if game not in allowed: return await i.response.send_message("❌ Unknown game. Choose a supported game.",ephemeral=True)
        sid=await db.new_session(i.guild_id,game,i.user.id,{"round":1,"seed":random.randint(1,999999)})
        if sid is None: return await i.response.send_message("⚠️ PostgreSQL is not connected. Set DATABASE_URL on Render.",ephemeral=True)
        view=LobbyView(game,sid)
        e=embed(f"{game.title()} • Lobby 🎮",f"**Session:** #{sid}\n\n📖 **How to play**\nYou have **30 seconds** to join. Press **🎮 Join Game**. When the timer ends, the game starts automatically. If nobody joins, it ends automatically.\n\n👤 Host: {i.user.mention}\n👥 Players: 1\n⏱️ Starting in: **30s**",discord.Color.blurple())
        e.add_field(name="🪙 Economy",value="Virtual coins + XP",inline=True)
        e.add_field(name="💾 Persistence",value="PostgreSQL",inline=True)
        await i.response.send_message(embed=e,view=view)
        await db.join_session(sid,i.user.id)
        msg=await i.original_response()
        asyncio.create_task(lobby_countdown(msg,game,sid,view))
    @bot.tree.command(name="play", description="Take a turn in a game session")
    @app_commands.describe(session_id="Session ID", decision="Your decision")
    async def play(i, session_id:int, decision:str):
        roll=random.randint(1,100); win=roll>=55
        outcome=random.choice(["Success!","Partial success.","A surprise event occurred!","You found a bonus!","The plan backfired — recover and continue."])
        coins=random.randint(10,40) if win else random.randint(2,12); xp=15 if win else 5
        await db.add_coins(i.guild_id,i.user.id,coins); await db.add_xp(i.guild_id,i.user.id,xp)
        e=embed("Game Turn 🎲",f"Session #{session_id}\\nDecision: {decision}",discord.Color.green() if win else discord.Color.orange())
        e.add_field(name="🎲 Roll",value=str(roll),inline=True); e.add_field(name="📜 Outcome",value=outcome,inline=False)
        e.add_field(name="🪙 Reward",value=f"+{coins} coins",inline=True); e.add_field(name="⭐ XP",value=f"+{xp} XP",inline=True)
        e.set_footer(text="Virtual gameplay • Rewards saved to profile"); await i.response.send_message(embed=e)

    @bot.tree.command(name="leaderboard", description="Show the server game leaderboard")
    async def leaderboard(i):
        if not db._pool: return await i.response.send_message(embed=embed("Leaderboard 🏆","Set DATABASE_URL on Render to enable persistent leaderboard data."))
        rows=await db._pool.fetch("SELECT user_id,coins,xp,level FROM players WHERE guild_id=$1 ORDER BY xp DESC,coins DESC LIMIT 10",i.guild_id)
        lines=[]
        for n,row in enumerate(rows,1):
            m=i.guild.get_member(row["user_id"]); name=m.display_name if m else f"User {row["user_id"]}"
            lines.append(f"**{n}.** {name} — ⭐ {row["xp"]} XP • 🪙 {row["coins"]} • Lv {row["level"]}")
        await i.response.send_message(embed=embed("AirCommander Leaderboard 🏆","\\n".join(lines) or "No players yet.",discord.Color.gold()))
    @bot.tree.command(name="profile", description="Show your persistent game profile")
    async def profile(i):
        p=await db.get_player(i.guild_id,i.user.id)
        e=embed("Player Profile 🧑‍✈️",f"{i.user.mention}'s AirCommander game profile")
        e.add_field(name="🪙 Coins",value=str(p["coins"]),inline=True)
        e.add_field(name="⭐ XP",value=str(p["xp"]),inline=True)
        e.add_field(name="🏅 Level",value=str(p["level"]),inline=True)
        await i.response.send_message(embed=e)

    @bot.tree.command(name="gamejoin", description="Join a game session")
    @app_commands.describe(session_id="Session ID")
    async def gamejoin(i,session_id:int):
        await db.join_session(session_id,i.user.id)
        e=embed("Game Lobby 🎮",f"{i.user.mention} joined session **#{session_id}**.",discord.Color.green())
        await i.response.send_message(embed=e)

    @bot.tree.command(name="whatif", description="Preview the possible result of an action")
    @app_commands.describe(action="Action to preview")
    async def whatif(i, action: str):
        outcomes=[("🟢 Low risk","Likely smooth; little disruption."),("🟡 Medium risk","Could affect members or channels; review permissions first."),("🔴 High risk","Potentially disruptive; verify target, permissions and rollback before applying.")]
        r=random.Random(seed(i.guild_id,action.lower())).choice(outcomes)
        e=embed("WhatIf • Action Preview",f"**Action:** {action}\n\n**Possible result:** {r[0]}\n{r[1]}\n\n*Preview only — nothing was changed.*")
        e.add_field(name="Safety",value="No Discord state was modified.",inline=False)
        await i.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name="impact", description="Estimate the server impact of an action")
    @app_commands.describe(action="Action to evaluate")
    async def impact(i, action: str):
        a=action.lower(); risk="Low"; score=20
        if any(x in a for x in ("ban","delete","remove","reset","lock","everyone")): risk="High"; score=85
        elif any(x in a for x in ("kick","mute","timeout","role","channel")): risk="Medium"; score=55
        e=embed("Impact Analysis",f"**{action}** is estimated at **{score}/100 impact** — **{risk}**.",discord.Color.orange() if risk!="Low" else discord.Color.green())
        e.add_field(name="👥 Members",value="May affect the selected target(s).",inline=True)
        e.add_field(name="📡 Server",value="Review permissions and scope.",inline=True)
        e.add_field(name="↩️ Recovery",value="Use /sandbox to preview before applying.",inline=False)
        await i.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name="sandbox", description="Preview a change without applying it")
    @app_commands.describe(change="Change to simulate")
    async def sandbox(i, change: str):
        e=embed("Sandbox • Dry Run",f"**Requested change:** {change}\n\n🧪 **Simulation complete.**\nNo members, roles, channels, permissions or messages were changed.",discord.Color.teal())
        e.add_field(name="Result",value="Preview generated successfully.",inline=False)
        await i.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name="blindspot", description="Find potential hidden configuration and security blind spots")
    async def blindspot(i):
        g=i.guild
        admins=[r for r in g.roles if r!=g.default_role and r.permissions.administrator]
        unc=[c for c in g.channels if getattr(c,"category",None) is None]
        e=embed("BlindSpot • Security Review","Potential issues visible from Discord configuration.",discord.Color.red())
        e.add_field(name="🔐 Administrator Roles",value=f"{len(admins)} non-default admin role(s) detected.",inline=True)
        e.add_field(name="📂 Uncategorized Channels",value=str(len(unc)),inline=True)
        e.add_field(name="⚠️ Review",value="Check powerful roles, channel overwrites, logging, bot permissions, and exposed management channels.",inline=False)
        e.set_footer(text="BlindSpot reports observable configuration; it cannot inspect third-party bot internals.")
        await i.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name="sequence", description="Build a preview workflow from multiple actions")
    @app_commands.describe(actions="Actions separated by commas")
    async def sequence(i, actions: str):
        steps=[x.strip() for x in actions.split(",") if x.strip()][:10]
        e=embed("Sequence • Workflow Preview","Automated workflow plan — **preview only**.",discord.Color.purple())
        e.add_field(name="Steps",value="\n".join(f"**{n}.** {x}" for n,x in enumerate(steps,1)) or "No actions supplied.",inline=False)
        e.add_field(name="Safety",value="No actions are executed by this command.",inline=False)
        await i.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name="roast", description="Give a playful fictional AI-style roast")
    @app_commands.describe(member="Member to roast")
    async def roast(i, member: discord.Member):
        lines=["has the confidence of a final boss and the aim of a tutorial bot.","could turn a 2-minute task into a three-season series.","is running on 2% battery and 98% audacity.","would lose a hide-and-seek match in an empty room.","has officially been diagnosed with terminal skill issue™."]
        e=embed("Roast Engine 🔥",f"{member.mention}, {random.choice(lines)}\n\n*Playful fictional roast — just for fun.*",discord.Color.orange())
        await i.response.send_message(embed=e)

    @bot.tree.command(name="ship", description="Calculate a funny compatibility percentage")
    @app_commands.describe(first="First member", second="Second member")
    async def ship(i, first: discord.Member, second: discord.Member):
        pct=seed(first.id,second.id)%101
        e=embed("Ship • Compatibility Scan",f"{first.mention} 💞 {second.mention}",discord.Color.magenta())
        e.add_field(name="❤️ Compatibility",value=f"**{pct}%**",inline=True)
        e.add_field(name="🔮 Verdict",value=random.Random(pct).choice(["Chaotic duo","Power couple","Besties energy","Rivals with chemistry","Absolutely unpredictable"]),inline=True)
        await i.response.send_message(embed=e)

    @bot.tree.command(name="chaos", description="Give a random safe challenge")
    async def chaos(i):
        challenges=["Compliment the next person who speaks.","Use only emojis for your next message.","Change your status to something funny for 10 minutes.","Ask the server a ridiculous but harmless question.","Send a wholesome meme."]
        e=embed("Chaos Challenge 🎲",random.choice(challenges),discord.Color.gold())
        e.set_footer(text="Safe challenge • No real-world or harmful actions")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="bounty", description="Place a virtual fun bounty on a member")
    @app_commands.describe(member="Target member", challenge="Bounty challenge", reward="Virtual reward points")
    async def bounty(i, member: discord.Member, challenge: str, reward: app_commands.Range[int,1,10000]=100):
        e=embed("Bounty Board 🎯",f"**Target:** {member.mention}\n**Challenge:** {challenge}\n**Reward:** 🪙 {reward} points",discord.Color.gold())
        e.set_footer(text="Virtual fun only • No real money or prizes")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="duel", description="Run a random stat-based virtual battle")
    @app_commands.describe(first="First fighter", second="Second fighter")
    async def duel(i, first: discord.Member, second: discord.Member):
        r=random.Random(seed(first.id,second.id)); a=r.randint(40,100); b=r.randint(40,100); winner=first if a>=b else second
        e=embed("Duel Arena ⚔️",f"{first.mention} **{a}**  VS  **{b}** {second.mention}",discord.Color.red())
        e.add_field(name="🏆 Winner",value=winner.mention,inline=False)
        await i.response.send_message(embed=e)

    @bot.tree.command(name="liecheck", description="Give a funny fictional truth probability")
    @app_commands.describe(statement="Statement to score")
    async def liecheck(i, statement: str):
        pct=seed(statement,i.user.id)%101
        e=embed("LieCheck 🕵️",f"**Statement:** {statement}",discord.Color.dark_teal())
        e.add_field(name="Truth Probability",value=f"**{pct}%**",inline=True)
        e.add_field(name="AI Verdict",value=random.Random(pct).choice(["Suspicious 👀","Seems believable","The bot is unconvinced","Probably true","Maximum cap detected"]),inline=True)
        e.set_footer(text="For entertainment only — not a real lie detector.")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="plot", description="Cast random server members into a funny story")
    async def plot(i):
        ms=[m for m in i.guild.members if not m.bot]
        random.shuffle(ms); ms=ms[:4]
        roles=["hero","mysterious wizard","chaotic sidekick","final boss"]
        story="\n".join(f"**{r.title()}:** {m.mention}" for r,m in zip(roles,ms))
        e=embed("Plot Generator 📖","Tonight's completely fictional server story:",discord.Color.purple())
        e.add_field(name="Cast",value=story or "Not enough members.",inline=False)
        await i.response.send_message(embed=e)

    @bot.tree.command(name="clone", description="Generate a funny fictional clone profile")
    @app_commands.describe(member="Member to clone")
    async def clone(i, member: discord.Member):
        traits=["+99 confidence","+80 snack detection","+100 chaos resistance","+42 tactical wisdom","-7 sleep schedule"]
        e=embed(f"Clone Lab 🧬 • {member.display_name}",f"**Fictional Clone Profile**\n\n"+ "\n".join(f"• {x}" for x in random.sample(traits,3)),discord.Color.teal())
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text="Fictional parody profile — not an impersonation tool.")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="wanted", description="Create a Wild-West style wanted profile")
    @app_commands.describe(member="Wanted member")
    async def wanted(i, member: discord.Member):
        e=embed("WANTED 🤠",f"**{member.display_name}**\n\nWanted for: **Being suspiciously funny**\nReward: **{seed(member.id)%5000+500} virtual coins**",discord.Color.dark_gold())
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text="Fictional server game • Not a real accusation")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="fortune", description="Generate a funny future prediction")
    async def fortune(i):
        e=embed("Fortune Oracle 🔮",random.choice(["A legendary ping will arrive soon.","You will find unexpected virtual treasure.","Someone will reply with exactly one emoji.","Your next message will start a chain of chaos.","The server's luck is watching you."]),discord.Color.purple())
        e.set_footer(text="For entertainment only")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="rival", description="Create a fictional rivalry between two members")
    @app_commands.describe(first="First member", second="Second member")
    async def rival(i, first: discord.Member, second: discord.Member):
        e=embed("Rivalry Generator ⚔️",f"{first.mention} 🆚 {second.mention}",discord.Color.red())
        e.add_field(name="Rivalry",value=random.choice(["Who owns the best profile?","Who can win the next challenge?","Who has superior meme energy?","Who will dominate the leaderboard?"]),inline=False)
        e.set_footer(text="Fictional rivalry • Keep it friendly")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="mission", description="Give a random mini-mission")
    async def mission(i):
        missions=["Help a new member.","Share a useful tip.","Win a friendly duel.","Earn three reactions.","Complete a community challenge."]
        m=random.choice(missions); pts=random.randint(10,100)
        e=embed("Mission Briefing 🎯",f"**Mission:** {m}\n**Reward:** 🪙 {pts} points",discord.Color.green())
        await i.response.send_message(embed=e)

    @bot.tree.command(name="roulette", description="Select a random safe server challenge")
    async def roulette(i):
        choices=["Tell a clean joke.","Use a random emoji in your next message.","Compliment someone.","Ask a fun question.","Post a harmless meme.","Challenge someone to /duel."]
        e=embed("Roulette 🎰",f"**Selected:** {random.choice(choices)}",discord.Color.gold())
        e.set_footer(text="Safe virtual challenge • No gambling or real-money rewards")
        await i.response.send_message(embed=e)

    @bot.tree.command(name="achievement", description="Check funny achievements")
    async def achievement(i):
        e=embed("Achievement Vault 🏆","Funny server achievements you can unlock.",discord.Color.gold())
        e.add_field(name="Available",value="🏅 First Flight\n🔥 Chaos Agent\n🕵️ Detective\n⚔️ Duelist\n💡 Idea Machine\n👑 Kingdom Builder",inline=False)
        await i.response.send_message(embed=e)

    @bot.tree.command(name="oracle", description="Give a dramatic random server prediction")
    async def oracle(i):
        e=embed("Oracle 🔮","The server whispers of **a great event approaching...**",discord.Color.purple())
        e.add_field(name="Prediction",value=random.choice(["A legendary member will appear.","A channel will become unexpectedly active.","The next challenge will change the leaderboard.","A forgotten role will return to glory."]),inline=False)
        e.set_footer(text="Dramatic fiction • Not a real prediction")
        await i.response.send_message(embed=e)

    games={
      "heist":("Heist 🏦","Build a crew, choose roles, and roll for a fictional heist outcome."),
      "kingdom":("Kingdom 👑","Build your virtual kingdom with resources, territory and upgrades."),
      "assassin":("Assassin 🥷","Join a fictional secret-target game and earn points through missions."),
      "blackmarket":("BlackMarket 🏪","Trade fictional items whose prices fluctuate with server activity."),
      "escape":("Escape Room 🔐","Solve fictional clues and puzzles to escape."),
      "outbreak":("Outbreak 🧟","Survive fictional rounds by managing resources."),
      "conquest":("Conquest 🗺️","Teams compete for fictional territories."),
      "treasure":("Treasure Hunt 🗺️","Discover fictional clues across server locations."),
      "arena":("Arena ⚔️","Create stats and fight turn-based fictional battles."),
      "casino":("Casino 🎲","Play fictional coin games with no real-money value."),
      "detective":("Detective 🕵️","Combine fictional clues and suspects to solve a case."),
      "zombie":("Zombie Survival 🧟","Choose a survivor class and face fictional zombie waves."),
      "race":("Virtual Race 🏁","Race with random events and obstacles."),
      "pirate":("Pirate Crew 🏴‍☠️","Build a crew, upgrade a ship and hunt fictional treasure."),
      "dungeon":("Dungeon 🏰","Multiplayer adventure with classes, loot, enemies and bosses.")
    }
    for name,(title,desc) in games.items():
        async def game_command(i, _title: str = title, _desc: str = desc):
            e=embed(_title,_desc,discord.Color.blurple())
            e.add_field(name="🎮 Status",value="Game module initialized — ready for the next turn.",inline=False)
            e.add_field(name="🪙 Economy",value="Virtual points only; no real-money value.",inline=False)
            e.set_footer(text="AirCommander Games • Friendly fictional gameplay")
            await i.response.send_message(embed=e)
        game_command.__name__=name
        game_command.__qualname__=name
        bot.tree.add_command(app_commands.Command(name=name,description=desc[:100],callback=game_command))
