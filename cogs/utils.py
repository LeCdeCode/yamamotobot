import os
import discord
from pathlib import Path
from datetime import datetime, timedelta
import json
from typing import Optional, List, Tuple

DATA_DIR = Path(os.getenv("DATA_DIR", os.getenv("RAILWAY_VOLUME_MOUNT_PATH", str(Path(__file__).parent.parent / "data"))))
DATA_DIR.mkdir(parents=True, exist_ok=True)

BANS_FILE           = DATA_DIR / "bans.json"
KICK_COOLDOWNS_FILE = DATA_DIR / "kick_cooldowns.json"
LEAVE_COOLDOWNS_FILE= DATA_DIR / "leave_cooldowns.json"
MEMBERS_FILE        = DATA_DIR / "members.json"
RANK_COOLDOWNS_FILE = DATA_DIR / "rank_cooldowns.json"
APPLICATIONS_FILE   = DATA_DIR / "applications.json"
CONFIGS_FILE        = DATA_DIR / "divisions_config.json"
COOLDOWNS_FILE      = DATA_DIR / "cooldowns.json"
PROFILES_FILE       = DATA_DIR / "member_profiles.json"
BLOCKS_FILE         = DATA_DIR / "blocks.json"

# ──────────────────────────────────────────────
# Configuration des divisions (source unique)
# ──────────────────────────────────────────────
DIVISIONS: dict[str, dict] = {
    "Division 1": {
        "role_id": 1520173789957062787,
        "channels": {
            "main":     1520182625807892550,
            "annonces": 1520182716794933408,
            "entrants": 1520183224561827870,
            "sortants": 1520183267230351370,
            "category": 1520176859818754189,
        },
    },
    "Division 6": {
        "role_id": 1520180291061415957,
        "channels": {
            "main":     1520185465817272391,
            "annonces": 1520185555516915913,
            "entrants": 1520185587926302730,
            "sortants": 1520185614081851453,
            "category": 1520176859818754189,
        },
    },
    "Division 10": {
        "role_id": 1520199862216425534,
        "channels": {
            "main":     1520194245997363341,
            "annonces": 1520199186916573335,
            "entrants": 1520199221268058172,
            "sortants": 1520199247822065854,
            "category": 1520176859818754189,
        },
    },
    "Division 11": {
        "role_id": 1520199922752819381,
        "channels": {
            "main":     1520199431532576788,
            "annonces": 1520213097376256081,
            "entrants": 1520213126799425747,
            "sortants": 1520213148865663017,
            "category": 1520176859818754189,
        },
    },
}

LIEUTENANT_ROLE_ID      = 1520240253628055572
VICE_CAPTAIN_ROLE_ID    = 1520180582120820856
DIVISION_CAPTAIN_ROLE_ID= 1520180582120820856

# ──────────────────────────────────────────────
# JSON helpers
# ──────────────────────────────────────────────

def load_json(file: Path) -> dict:
    if file.exists():
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}

def save_json(file: Path, data: dict) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(file)

# ──────────────────────────────────────────────
# Division helpers
# ──────────────────────────────────────────────

def get_division_by_member(member: discord.Member) -> Optional[Tuple[str, dict]]:
    for div_name, div_data in DIVISIONS.items():
        role = member.guild.get_role(div_data["role_id"])
        if role and role in member.roles:
            return (div_name, div_data)
    return None

def get_division_number(division_name: str) -> str:
    return division_name.split()[-1]

def count_division_members(guild: discord.Guild, division_name: str) -> int:
    div_data = DIVISIONS.get(division_name)
    if not div_data:
        return 0
    role = guild.get_role(div_data["role_id"])
    return len(role.members) if role else 0

# ──────────────────────────────────────────────
# Ban helpers
# ──────────────────────────────────────────────

def is_member_banned(member_id: int) -> bool:
    bans = load_json(BANS_FILE)
    return str(member_id) in bans

def ban_member(member_id: int) -> None:
    bans = load_json(BANS_FILE)
    bans[str(member_id)] = datetime.now().isoformat()
    save_json(BANS_FILE, bans)

def unban_member(member_id: int) -> None:
    bans = load_json(BANS_FILE)
    bans.pop(str(member_id), None)
    save_json(BANS_FILE, bans)

# ──────────────────────────────────────────────
# Cooldown helpers
# ──────────────────────────────────────────────

def can_rejoin_after_kick(member_id: int, division_name: str) -> bool:
    cooldowns = load_json(KICK_COOLDOWNS_FILE)
    key = f"{member_id}_{division_name}"
    if key not in cooldowns:
        return True
    last_kick = datetime.fromisoformat(cooldowns[key])
    return datetime.now() >= last_kick + timedelta(days=3)

def set_kick_cooldown(member_id: int, division_name: str) -> None:
    cooldowns = load_json(KICK_COOLDOWNS_FILE)
    cooldowns[f"{member_id}_{division_name}"] = datetime.now().isoformat()
    save_json(KICK_COOLDOWNS_FILE, cooldowns)

def can_rejoin_after_leave(member_id: int) -> bool:
    cooldowns = load_json(LEAVE_COOLDOWNS_FILE)
    if str(member_id) not in cooldowns:
        return True
    last_leave = datetime.fromisoformat(cooldowns[str(member_id)])
    return datetime.now() >= last_leave + timedelta(days=3)

def set_leave_cooldown(member_id: int) -> None:
    cooldowns = load_json(LEAVE_COOLDOWNS_FILE)
    cooldowns[str(member_id)] = datetime.now().isoformat()
    save_json(LEAVE_COOLDOWNS_FILE, cooldowns)

# ──────────────────────────────────────────────
# Member data helpers
# ──────────────────────────────────────────────

def add_member_to_division(member_id: int, division_name: str, join_date: str = None) -> None:
    members = load_json(MEMBERS_FILE)
    key = f"{member_id}_{division_name}"
    members[key] = {
        "join_date": join_date or datetime.now().isoformat(),
        "division": division_name,
        "rank": None,
    }
    save_json(MEMBERS_FILE, members)

def remove_member_from_division(member_id: int, division_name: str) -> None:
    members = load_json(MEMBERS_FILE)
    members.pop(f"{member_id}_{division_name}", None)
    save_json(MEMBERS_FILE, members)

def get_member_divisions(member_id: int) -> List[str]:
    members = load_json(MEMBERS_FILE)
    return [data["division"] for key, data in members.items() if key.startswith(f"{member_id}_")]

def get_member_rank(member_id: int, division_name: str) -> Optional[str]:
    members = load_json(MEMBERS_FILE)
    return members.get(f"{member_id}_{division_name}", {}).get("rank")

def set_member_rank(member_id: int, division_name: str, rank: Optional[str]) -> None:
    members = load_json(MEMBERS_FILE)
    key = f"{member_id}_{division_name}"
    if key in members:
        members[key]["rank"] = rank
        save_json(MEMBERS_FILE, members)

def get_member_join_date(member_id: int, division_name: str) -> Optional[str]:
    members = load_json(MEMBERS_FILE)
    return members.get(f"{member_id}_{division_name}", {}).get("join_date")

# ──────────────────────────────────────────────
# Rank cooldowns
# ──────────────────────────────────────────────

def can_rank(captain_id: int, division_name: str, rank_type: int) -> bool:
    cooldowns = load_json(RANK_COOLDOWNS_FILE)
    key = f"{captain_id}_{division_name}_rank{rank_type}"
    if key not in cooldowns:
        return True
    last_rank = datetime.fromisoformat(cooldowns[key])
    return datetime.now() >= last_rank + timedelta(days=10)

def set_rank_cooldown(captain_id: int, division_name: str, rank_type: int) -> None:
    cooldowns = load_json(RANK_COOLDOWNS_FILE)
    cooldowns[f"{captain_id}_{division_name}_rank{rank_type}"] = datetime.now().isoformat()
    save_json(RANK_COOLDOWNS_FILE, cooldowns)

def get_rank_holder(guild: discord.Guild, division_name: str, rank_type: int) -> Optional[discord.Member]:
    role_id = LIEUTENANT_ROLE_ID if rank_type == 1 else (VICE_CAPTAIN_ROLE_ID if rank_type == 2 else None)
    if not role_id:
        return None
    role = guild.get_role(role_id)
    if not role:
        return None
    members = load_json(MEMBERS_FILE)
    for member in role.members:
        if f"{member.id}_{division_name}" in members:
            return member
    return None

# ──────────────────────────────────────────────
# Block helpers
# ──────────────────────────────────────────────

def is_member_blocked(member_id: int, division_name: str) -> bool:
    blocks = load_json(BLOCKS_FILE)
    return division_name in blocks.get(str(member_id), [])

def block_member_from_division(member_id: int, division_name: str) -> None:
    blocks = load_json(BLOCKS_FILE)
    key = str(member_id)
    if key not in blocks:
        blocks[key] = []
    if division_name not in blocks[key]:
        blocks[key].append(division_name)
    save_json(BLOCKS_FILE, blocks)

def unblock_member_from_division(member_id: int, division_name: str) -> None:
    blocks = load_json(BLOCKS_FILE)
    key = str(member_id)
    if key in blocks:
        blocks[key] = [d for d in blocks[key] if d != division_name]
        if not blocks[key]:
            del blocks[key]
    save_json(BLOCKS_FILE, blocks)

def get_blocked_divisions(member_id: int) -> List[str]:
    return load_json(BLOCKS_FILE).get(str(member_id), [])

# ──────────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────────

def load_division_config(division_name: str) -> dict:
    return load_json(CONFIGS_FILE).get(division_name, {})

def save_division_config(division_name: str, config: dict) -> None:
    configs = load_json(CONFIGS_FILE)
    configs[division_name] = config
    save_json(CONFIGS_FILE, configs)

def check_cooldown_config(captain_id: int, division_name: str, cooldown_days: int):
    from datetime import datetime, timedelta
    cooldowns = load_json(COOLDOWNS_FILE)
    key = f"{captain_id}_{division_name}"
    last_update = cooldowns.get(key)
    if not last_update:
        return None
    last_time = datetime.fromisoformat(last_update)
    next_allowed = last_time + timedelta(days=cooldown_days)
    if datetime.now() < next_allowed:
        return next_allowed
    return None

def set_cooldown_config(captain_id: int, division_name: str) -> None:
    cooldowns = load_json(COOLDOWNS_FILE)
    cooldowns[f"{captain_id}_{division_name}"] = datetime.now().isoformat()
    save_json(COOLDOWNS_FILE, cooldowns)

# ──────────────────────────────────────────────
# Welcome/Goodbye message helpers
# ──────────────────────────────────────────────

def get_welcome_message(division_name: str) -> str:
    config = load_division_config(division_name)
    return config.get("welcome_message", f"🎉 Bienvenue à {{member}} dans **{division_name}** !")

def set_welcome_message(division_name: str, message: str) -> None:
    config = load_division_config(division_name)
    config["welcome_message"] = message
    save_division_config(division_name, config)

def get_goodbye_message(division_name: str) -> str:
    config = load_division_config(division_name)
    return config.get("goodbye_message", f"👋 {{member}} a quitté **{division_name}**.")

def set_goodbye_message(division_name: str, message: str) -> None:
    config = load_division_config(division_name)
    config["goodbye_message"] = message
    save_division_config(division_name, config)

# ──────────────────────────────────────────────
# Announcement senders (for join/leave)
# ──────────────────────────────────────────────

async def send_join_announcement(guild: discord.Guild, member: discord.Member, division_name: str) -> None:
    """Envoie un message de bienvenue dans le salon 'entrants' de la division."""
    data = DIVISIONS.get(division_name)
    if not data:
        return
    channel = guild.get_channel(data["channels"]["entrants"])
    if not channel:
        return
    embed = discord.Embed(
        title="🎉 Nouveau membre",
        description=f"Bienvenue à {member.mention} dans **{division_name}** !",
        color=discord.Color.green(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass

async def send_leave_announcement(guild: discord.Guild, member: discord.Member, division_name: str) -> None:
    """Envoie un message d'au revoir dans le salon 'sortants' de la division."""
    data = DIVISIONS.get(division_name)
    if not data:
        return
    channel = guild.get_channel(data["channels"]["sortants"])
    if not channel:
        return
    embed = discord.Embed(
        title="👋 Membre parti",
        description=f"{member.mention} a quitté **{division_name}**.",
        color=discord.Color.red(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass
