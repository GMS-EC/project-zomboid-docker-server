import re
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.config import settings
from app.core.fs_utils import atomic_write_text
from app.core.activity_manager import activity_manager


# Valores predeterminados oficiales para <SERVER_NAME>.ini
DEFAULT_INI_SETTINGS: Dict[str, str] = {
    # Identidad y Acceso
    "PublicName": "Project Zomboid Server",
    "PublicDescription": "Servidor Dedicado de Project Zomboid gestionado vía Panel Web.",
    "ServerWelcomeMessage": "¡Bienvenido al servidor de Project Zomboid! Sobrevive y colabora con otros supervivientes.",
    "Password": "",
    "AdminPassword": "adminpass",
    "MaxPlayers": "16",
    "Public": "false",
    "Open": "true",
    "AutoCreateUserInWhiteList": "false",
    "DropOffWhiteListAfter": "0",
    "PauseEmpty": "true",
    "PingLimit": "400",
    "DenyLoginOnOverloadedServer": "true",
    "DoLuaChecksum": "true",

    # PvP y Combate
    "PVP": "true",
    "SafetySystem": "true",
    "ShowSafety": "true",
    "SafetyToggleTimer": "2",
    "SafetyCooldownTimer": "120",

    # Refugios (Safehouses)
    "PlayerSafehouse": "true",
    "AdminSafehouse": "false",
    "SafehouseAllowTrepass": "false",
    "SafehouseAllowFire": "false",
    "SafehouseAllowLoot": "false",
    "SafehouseAllowRespawn": "false",
    "SafehouseDaySurvivedToClaim": "0",
    "SafehouseAllowNonMembers": "false",

    # Facciones
    "Faction": "true",
    "FactionDaySurvivedToCreate": "0",
    "FactionPlayersRequiredForTag": "1",

    # Rendimiento y Backups
    "FastForwardMultiplier": "40.0",
    "BackupsOnStart": "true",
    "BackupsOnVersionChange": "true",
    "BackupsPeriod": "0",
    "BackupsCount": "5",

    # Supervivencia, Sueño y Chat
    "SleepAllowed": "false",
    "SleepNeeded": "false",
    "SteamVAC": "true",
    "SteamScoreboard": "true",
    "DisplayUserName": "true",
    "ShowFirstAndLastName": "false",
    "VoiceEnable": "true",
    "Voice3D": "true",
    "SpeedLimit": "70.0",
    "GlobalChat": "true",
    "ChatStreams": "s,r,a,w,g",
    "ItemNumbersLimitPerContainer": "0",
    "BloodSplatLifespanDays": "0",
    "AllowDestructionBySledgehammer": "true",
    "SledgehammerOnlyInSafehouse": "false",

    # Respawn de Botín
    "HoursForLootRespawn": "0",
    "MaxItemsForLootRespawn": "0",
    "ConstructionPreventsLootRespawn": "true",

    # Mapa y Generación
    "Map": "Muldraugh, KY",
    "SpawnPoint": "0,0,0",
    "SpawnItems": "",
    "DefaultPort": "16261",
    "UDPPort": "16262",
    "RCONPort": "27015",
    "RCONPassword": "",
    "WorkshopItems": "",
    "Mods": "",
}

# Valores predeterminados para SandboxVars.lua
DEFAULT_SANDBOX_SETTINGS: Dict[str, Any] = {
    # ZombieLore
    "zombie_speed": 2,          # 1=Sprinters, 2=Fast Shamblers, 3=Shamblers
    "zombie_strength": 2,       # 1=Superhuman, 2=Normal, 3=Weak
    "zombie_toughness": 2,      # 1=Tough, 2=Normal, 3=Fragile
    "zombie_transmission": 1,   # 1=Blood+Saliva, 2=Saliva, 3=None
    "zombie_mortality": 5,      # 1=Instant, 2=0-30s, 3=0-1m, 4=0-12h, 5=2-3d, 6=1-2w, 7=Never
    "zombie_reanimate": 3,      # 1=Instant, 2=0-30s, 3=0-1m, 4=0-12h, 5=2-3d, 6=1-2w
    "zombie_cognition": 3,      # 1=Navigate+Doors, 2=Navigate, 3=Basic
    "zombie_crawl": 5,          # 1=Always, 2=Often, 3=Very Often, 4=Rare, 5=Never
    "zombie_memory": 2,         # 1=Long, 2=Normal, 3=Short, 4=None
    "zombie_decomp": 1,         # 1=Decay Slows+Weakens, 2=Slows, 3=Weakens, 4=No Effect
    "zombie_sight": 2,          # 1=Eagle, 2=Normal, 3=Poor
    "zombie_hearing": 2,        # 1=Pinpoint, 2=Normal, 3=Poor
    "zombie_smell": 2,          # 1=Bloodhound, 2=Normal, 3=Poor
    "zombie_thump_no_chase": False,
    "zombie_house_alarm": False,
    "zombie_active_only": 1,    # 1=Both Day and Night, 2=Night, 3=Day

    # ZombieConfig (Población)
    "pop_multiplier": 1.0,
    "pop_start_multiplier": 1.0,
    "pop_peak_multiplier": 1.5,
    "pop_peak_day": 28,
    "respawn_multiplier": 0.1,
    "respawn_hours": 72.0,
    "respawn_unseen_hours": 16.0,
    "redistribute_hours": 12.0,
    "follow_sound_dist": 100,
    "rally_group_size": 20,
    "rally_travel_dist": 20,
    "rally_group_sep": 15,
    "rally_group_radius": 3,

    # Entorno y Tiempo
    "day_length": 2,            # 1=30m, 2=1h, 3=2h, 4=3h, 5=4h, 6=5h
    "start_month": 7,           # 1-12
    "start_day": 9,
    "start_time": 2,            # 1=7am, 2=9am, 3=12pm, 4=2pm, 5=5pm, 6=9pm, 7=12am, 8=2am, 9=5am
    "water_shut": 2,            # 1=Instant, 2=0-30d, 3=0-2m, 4=0-6m, 5=0-1y, 6=0-5y, 7=2-6m, 8=Never
    "elec_shut": 2,             # 1=Instant, 2=0-30d, etc.
    "water_shut_modifier": 14,
    "elec_shut_modifier": 14,
    "temperature": 3,           # 1=Very Cold, 2=Cold, 3=Normal, 4=Hot, 5=Very Hot
    "rain": 3,                  # 1=Very Dry, 2=Dry, 3=Normal, 4=Rainy, 5=Very Rainy
    "erosion_speed": 3,         # 1=Very Fast (20d), 2=Fast (50d), 3=Normal (100d), 4=Slow (200d), 5=Very Slow
    "erosion_days": 100,
    "farming": 3,               # 1=Very Fast, 2=Fast, 3=Normal, 4=Slow, 5=Very Slow
    "plant_resilience": 3,      # 1=Very High, 2=High, 3=Normal, 4=Low, 5=Very Low
    "plant_abundance": 3,       # 1=Very Poor, 2=Poor, 3=Normal, 4=Abundant, 5=Very Abundant
    "nature_abundance": 3,      # 1=Very Poor, 2=Poor, 3=Normal, 4=Abundant, 5=Very Abundant
    "compost_time": 2,          # 1=1w, 2=2w, 3=3w, 4=4w, 5=6w, 6=8w, 7=10w, 8=12w
    "darkness": 3,              # 1=Pitch Black, 2=Dark, 3=Normal
    "fire_spread": True,

    # Botín (Loot Rarity: 1=Extremely Rare, 2=Rare, 3=Normal, 4=Common, 5=Abundant)
    "loot_food": 3,
    "loot_canned_food": 3,
    "loot_literature": 3,
    "loot_survival": 3,
    "loot_medical": 3,
    "loot_weapon": 3,
    "loot_ranged_weapon": 3,
    "loot_ammo": 3,
    "loot_mechanics": 3,
    "loot_other": 3,

    # Personaje y Rasgos
    "xp_multiplier": 1.0,
    "multi_hit_zombies": True,  # Multi-Hit con armas cuerpo a cuerpo
    "stats_decrease": 3,        # 1=Very Fast, 2=Fast, 3=Normal, 4=Slow, 5=Very Slow
    "endurance_regen": 3,
    "nutrition": True,
    "starter_kit": False,
    "free_trait_points": 0,
    "injury_severity": 2,       # 1=Low, 2=Normal, 3=High
    "bone_fracture": True,
    "rear_vulnerability": 2,    # 1=Low, 2=Medium, 3=High

    # Vehículos
    "enable_vehicles": True,
    "car_spawn_rate": 3,        # 1=None, 2=Very Low, 3=Low, 4=Normal, 5=High
    "chance_has_gas": 2,        # 1=Low, 2=Normal, 3=High
    "initial_gas": 2,           # 1=Very Low, 2=Low, 3=Normal, 4=High, 5=Full
    "fuel_consumption": 1.0,
    "car_gas_consumption": 1.0,
    "car_alarm_freq": 2,        # 1=Never, 2=Extremely Rare, 3=Rare, 4=Normal, 5=Common
    "locked_car": 3,
    "car_condition": 2,         # 1=Very Low, 2=Low, 3=Normal, 4=High
    "car_damage_impact": 3,
    "crash_player_damage": True,
    "traffic_jam": True,
    "zombie_attraction_multiplier": 1.0,

    # Meta-Eventos, Historias y Generadores
    "helicopter": 2,            # 1=Never, 2=Once, 3=Sometimes, 4=Often
    "meta_event": 2,            # 1=Never, 2=Sometimes, 3=Often
    "sleeping_event": 2,
    "survivor_house_chance": 3, # 1=Never, 2=Extremely Rare, 3=Rare, 4=Normal, 5=Often, 6=Very Often
    "vehicle_story_chance": 3,
    "zone_story_chance": 3,
    "generator_spawning": 3,    # 1=Very Rare, 2=Rare, 3=Sometimes, 4=Often
    "generator_fuel_consumption": 1.0,

    # Mapa en el Juego
    "allow_mini_map": True,
    "allow_world_map": True,
    "map_all_known": False,
}


def _lua_format_val(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        if val.lower() in ("true", "false"):
            return val.lower()
        try:
            if "." in val:
                float(val)
                return val
            int(val)
            return val
        except ValueError:
            safe = val.replace('"', '\\"')
            return f'"{safe}"'
    return str(val)


def generate_default_lua(values: Dict[str, Any]) -> str:
    v = {**DEFAULT_SANDBOX_SETTINGS, **values}
    fmt = _lua_format_val
    return f"""SandboxVars = {{
    VERSION = 5,
    Speed = 3,
    ZombieLore = {{
        Speed = {fmt(v['zombie_speed'])},
        Strength = {fmt(v['zombie_strength'])},
        Toughness = {fmt(v['zombie_toughness'])},
        Transmission = {fmt(v['zombie_transmission'])},
        Mortality = {fmt(v['zombie_mortality'])},
        Reanimate = {fmt(v['zombie_reanimate'])},
        Cognition = {fmt(v['zombie_cognition'])},
        CrawlUnderVehicle = {fmt(v['zombie_crawl'])},
        Memory = {fmt(v['zombie_memory'])},
        Decomp = {fmt(v['zombie_decomp'])},
        Sight = {fmt(v['zombie_sight'])},
        Hearing = {fmt(v['zombie_hearing'])},
        Smell = {fmt(v['zombie_smell'])},
        ThumpNoChasing = {fmt(v['zombie_thump_no_chase'])},
        TriggerHouseAlarm = {fmt(v['zombie_house_alarm'])},
        ActiveOnly = {fmt(v['zombie_active_only'])},
    }},
    ZombieConfig = {{
        PopulationMultiplier = {fmt(v['pop_multiplier'])},
        PopulationStartMultiplier = {fmt(v['pop_start_multiplier'])},
        PopulationPeakMultiplier = {fmt(v['pop_peak_multiplier'])},
        PopulationPeakDay = {fmt(v['pop_peak_day'])},
        RespawnMultiplier = {fmt(v['respawn_multiplier'])},
        RespawnHours = {fmt(v['respawn_hours'])},
        RespawnUnseenHours = {fmt(v['respawn_unseen_hours'])},
        RedistributeHours = {fmt(v['redistribute_hours'])},
        FollowSoundDistance = {fmt(v['follow_sound_dist'])},
        RallyGroupSize = {fmt(v['rally_group_size'])},
        RallyTravelDistance = {fmt(v['rally_travel_dist'])},
        RallyGroupSeparation = {fmt(v['rally_group_sep'])},
        RallyGroupRadius = {fmt(v['rally_group_radius'])},
    }},
    DayLength = {fmt(v['day_length'])},
    StartYear = 1,
    StartMonth = {fmt(v['start_month'])},
    StartDay = {fmt(v['start_day'])},
    StartTime = {fmt(v['start_time'])},
    WaterShut = {fmt(v['water_shut'])},
    ElecShut = {fmt(v['elec_shut'])},
    WaterShutModifier = {fmt(v['water_shut_modifier'])},
    ElecShutModifier = {fmt(v['elec_shut_modifier'])},
    FoodLoot = {fmt(v['loot_food'])},
    CannedFoodLoot = {fmt(v['loot_canned_food'])},
    LiteratureLoot = {fmt(v['loot_literature'])},
    SurvivalGearsLoot = {fmt(v['loot_survival'])},
    MedicalLoot = {fmt(v['loot_medical'])},
    WeaponLoot = {fmt(v['loot_weapon'])},
    RangedWeaponLoot = {fmt(v['loot_ranged_weapon'])},
    AmmoLoot = {fmt(v['loot_ammo'])},
    MechanicsLoot = {fmt(v['loot_mechanics'])},
    OtherLoot = {fmt(v['loot_other'])},
    Temperature = {fmt(v['temperature'])},
    Rain = {fmt(v['rain'])},
    ErosionSpeed = {fmt(v['erosion_speed'])},
    ErosionDays = {fmt(v['erosion_days'])},
    Farming = {fmt(v['farming'])},
    PlantResilience = {fmt(v['plant_resilience'])},
    PlantAbundance = {fmt(v['plant_abundance'])},
    NatureAbundance = {fmt(v['nature_abundance'])},
    CompostTime = {fmt(v['compost_time'])},
    NightDarkness = {fmt(v['darkness'])},
    FireSpread = {fmt(v['fire_spread'])},
    XPMultiplier = {fmt(v['xp_multiplier'])},
    MultiHitZombies = {fmt(v['multi_hit_zombies'])},
    StatsDecrease = {fmt(v['stats_decrease'])},
    EnduranceRegen = {fmt(v['endurance_regen'])},
    Nutrition = {fmt(v['nutrition'])},
    StarterKit = {fmt(v['starter_kit'])},
    CharacterFreePoints = {fmt(v['free_trait_points'])},
    InjurySeverity = {fmt(v['injury_severity'])},
    BoneFracture = {fmt(v['bone_fracture'])},
    RearVulnerability = {fmt(v['rear_vulnerability'])},
    EnableVehicles = {fmt(v['enable_vehicles'])},
    CarSpawnRate = {fmt(v['car_spawn_rate'])},
    ChanceHasGas = {fmt(v['chance_has_gas'])},
    InitialGas = {fmt(v['initial_gas'])},
    FuelConsumption = {fmt(v['fuel_consumption'])},
    CarGasConsumption = {fmt(v['car_gas_consumption'])},
    CarAlarmFrequency = {fmt(v['car_alarm_freq'])},
    LockedCar = {fmt(v['locked_car'])},
    CarGeneralCondition = {fmt(v['car_condition'])},
    CarDamageOnImpact = {fmt(v['car_damage_impact'])},
    DamageToPlayerFromCarCrash = {fmt(v['crash_player_damage'])},
    TrafficJam = {fmt(v['traffic_jam'])},
    ZombieAttractionMultiplier = {fmt(v['zombie_attraction_multiplier'])},
    SurvivorHouseChance = {fmt(v['survivor_house_chance'])},
    VehicleStoryChance = {fmt(v['vehicle_story_chance'])},
    ZoneStoryChance = {fmt(v['zone_story_chance'])},
    Helicopter = {fmt(v['helicopter'])},
    MetaEvent = {fmt(v['meta_event'])},
    SleepingEvent = {fmt(v['sleeping_event'])},
    GeneratorSpawning = {fmt(v['generator_spawning'])},
    GeneratorFuelConsumption = {fmt(v['generator_fuel_consumption'])},
    Map = {{
        AllowMiniMap = {fmt(v['allow_mini_map'])},
        AllowWorldMap = {fmt(v['allow_world_map'])},
        MapAllKnown = {fmt(v['map_all_known'])},
    }},
}}
"""


class PzSettingsManager:
    """
    Gestor integral de opciones de Project Zomboid Dedicated Server:
      - <SERVER_NAME>.ini (Identidad, red, PvP, Safehouses, chat, motor)
      - <SERVER_NAME>_SandboxVars.lua (Dificultad, zombis, botín, vehículos, entorno)
      - pz_panel_config.json (Memoria JVM -Xms/-Xmx, autoinicio, modo Steam/No-Steam)
    """

    @property
    def ini_path(self) -> Path:
        return settings.data_dir / "Server" / f"{settings.server_name}.ini"

    @property
    def sandbox_path(self) -> Path:
        return settings.data_dir / "Server" / f"{settings.server_name}_SandboxVars.lua"

    # ------------------------------------------------------------- Lectura / Escritura INI
    def read_ini(self) -> Dict[str, str]:
        data = dict(DEFAULT_INI_SETTINGS)
        if self.ini_path.exists():
            try:
                for raw in self.ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = raw.strip()
                    if not line or line.startswith(("#", ";", "[")):
                        continue
                    if "=" in line:
                        key, _, val = line.partition("=")
                        data[key.strip()] = val.strip()
            except Exception:
                pass
        return data

    def set_ini_values(self, values: Dict[str, str]) -> bool:
        """Sobrescribe o inserta claves en el .ini conservando el resto."""
        try:
            self.ini_path.parent.mkdir(parents=True, exist_ok=True)
            current = self.read_ini()
            current.update({k: str(v) for k, v in values.items() if v is not None})
            lines = [f"{k}={current[k]}" for k in sorted(current.keys())]
            atomic_write_text(self.ini_path, "\n".join(lines) + "\n")
            return True
        except Exception:
            return False

    def get_raw_ini(self) -> str:
        if self.ini_path.exists():
            try:
                return self.ini_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        lines = [f"{k}={v}" for k, v in sorted(DEFAULT_INI_SETTINGS.items())]
        return "\n".join(lines) + "\n"

    def save_raw_ini(self, content: str) -> bool:
        try:
            self.ini_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.ini_path, content)
            activity_manager.log("Configuración", "Archivo .ini actualizado directamente")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------- Lectura / Escritura LUA
    def read_sandbox(self) -> Dict[str, Any]:
        data = dict(DEFAULT_SANDBOX_SETTINGS)
        if not self.sandbox_path.exists():
            return data

        try:
            text = self.sandbox_path.read_text(encoding="utf-8", errors="replace")
            # Buscar cada token en el archivo Lua
            token_map = {
                "zombie_speed": r"ZombieLore\s*=\s*\{[^}]*Speed\s*=\s*(\d+)",
                "zombie_strength": r"ZombieLore\s*=\s*\{[^}]*Strength\s*=\s*(\d+)",
                "zombie_toughness": r"ZombieLore\s*=\s*\{[^}]*Toughness\s*=\s*(\d+)",
                "zombie_transmission": r"ZombieLore\s*=\s*\{[^}]*Transmission\s*=\s*(\d+)",
                "zombie_mortality": r"ZombieLore\s*=\s*\{[^}]*Mortality\s*=\s*(\d+)",
                "zombie_reanimate": r"ZombieLore\s*=\s*\{[^}]*Reanimate\s*=\s*(\d+)",
                "zombie_cognition": r"ZombieLore\s*=\s*\{[^}]*Cognition\s*=\s*(\d+)",
                "zombie_crawl": r"ZombieLore\s*=\s*\{[^}]*CrawlUnderVehicle\s*=\s*(\d+)",
                "zombie_memory": r"ZombieLore\s*=\s*\{[^}]*Memory\s*=\s*(\d+)",
                "zombie_decomp": r"ZombieLore\s*=\s*\{[^}]*Decomp\s*=\s*(\d+)",
                "zombie_sight": r"ZombieLore\s*=\s*\{[^}]*Sight\s*=\s*(\d+)",
                "zombie_hearing": r"ZombieLore\s*=\s*\{[^}]*Hearing\s*=\s*(\d+)",
                "zombie_smell": r"ZombieLore\s*=\s*\{[^}]*Smell\s*=\s*(\d+)",
                "zombie_thump_no_chase": r"ZombieLore\s*=\s*\{[^}]*ThumpNoChasing\s*=\s*(\w+)",
                "zombie_house_alarm": r"ZombieLore\s*=\s*\{[^}]*TriggerHouseAlarm\s*=\s*(\w+)",
                "zombie_active_only": r"ZombieLore\s*=\s*\{[^}]*ActiveOnly\s*=\s*(\d+)",

                "pop_multiplier": r"ZombieConfig\s*=\s*\{[^}]*PopulationMultiplier\s*=\s*([\d\.]+)",
                "pop_start_multiplier": r"ZombieConfig\s*=\s*\{[^}]*PopulationStartMultiplier\s*=\s*([\d\.]+)",
                "pop_peak_multiplier": r"ZombieConfig\s*=\s*\{[^}]*PopulationPeakMultiplier\s*=\s*([\d\.]+)",
                "pop_peak_day": r"ZombieConfig\s*=\s*\{[^}]*PopulationPeakDay\s*=\s*(\d+)",
                "respawn_multiplier": r"ZombieConfig\s*=\s*\{[^}]*RespawnMultiplier\s*=\s*([\d\.]+)",
                "respawn_hours": r"ZombieConfig\s*=\s*\{[^}]*RespawnHours\s*=\s*([\d\.]+)",
                "respawn_unseen_hours": r"ZombieConfig\s*=\s*\{[^}]*RespawnUnseenHours\s*=\s*([\d\.]+)",
                "redistribute_hours": r"ZombieConfig\s*=\s*\{[^}]*RedistributeHours\s*=\s*([\d\.]+)",
                "follow_sound_dist": r"ZombieConfig\s*=\s*\{[^}]*FollowSoundDistance\s*=\s*(\d+)",
                "rally_group_size": r"ZombieConfig\s*=\s*\{[^}]*RallyGroupSize\s*=\s*(\d+)",

                "day_length": r"\bDayLength\s*=\s*(\d+)",
                "start_month": r"\bStartMonth\s*=\s*(\d+)",
                "start_day": r"\bStartDay\s*=\s*(\d+)",
                "start_time": r"\bStartTime\s*=\s*(\d+)",
                "water_shut": r"\bWaterShut\s*=\s*(\d+)",
                "elec_shut": r"\bElecShut\s*=\s*(\d+)",
                "water_shut_modifier": r"\bWaterShutModifier\s*=\s*(\d+)",
                "elec_shut_modifier": r"\bElecShutModifier\s*=\s*(\d+)",

                "loot_food": r"\bFoodLoot\s*=\s*(\d+)",
                "loot_canned_food": r"\bCannedFoodLoot\s*=\s*(\d+)",
                "loot_literature": r"\bLiteratureLoot\s*=\s*(\d+)",
                "loot_survival": r"\bSurvivalGearsLoot\s*=\s*(\d+)",
                "loot_medical": r"\bMedicalLoot\s*=\s*(\d+)",
                "loot_weapon": r"\bWeaponLoot\s*=\s*(\d+)",
                "loot_ranged_weapon": r"\bRangedWeaponLoot\s*=\s*(\d+)",
                "loot_ammo": r"\bAmmoLoot\s*=\s*(\d+)",
                "loot_mechanics": r"\bMechanicsLoot\s*=\s*(\d+)",
                "loot_other": r"\bOtherLoot\s*=\s*(\d+)",

                "temperature": r"\bTemperature\s*=\s*(\d+)",
                "rain": r"\bRain\s*=\s*(\d+)",
                "erosion_speed": r"\bErosionSpeed\s*=\s*(\d+)",
                "erosion_days": r"\bErosionDays\s*=\s*(\d+)",
                "farming": r"\bFarming\s*=\s*(\d+)",
                "plant_resilience": r"\bPlantResilience\s*=\s*(\d+)",
                "plant_abundance": r"\bPlantAbundance\s*=\s*(\d+)",
                "nature_abundance": r"\bNatureAbundance\s*=\s*(\d+)",
                "compost_time": r"\bCompostTime\s*=\s*(\d+)",
                "darkness": r"\bNightDarkness\s*=\s*(\d+)",
                "fire_spread": r"\bFireSpread\s*=\s*(\w+)",

                "xp_multiplier": r"\bXPMultiplier\s*=\s*([\d\.]+)",
                "multi_hit_zombies": r"\bMultiHitZombies\s*=\s*(\w+)",
                "stats_decrease": r"\bStatsDecrease\s*=\s*(\d+)",
                "endurance_regen": r"\bEnduranceRegen\s*=\s*(\d+)",
                "nutrition": r"\bNutrition\s*=\s*(\w+)",
                "starter_kit": r"\bStarterKit\s*=\s*(\w+)",
                "free_trait_points": r"\bCharacterFreePoints\s*=\s*(\d+)",
                "injury_severity": r"\bInjurySeverity\s*=\s*(\d+)",
                "bone_fracture": r"\bBoneFracture\s*=\s*(\w+)",
                "rear_vulnerability": r"\bRearVulnerability\s*=\s*(\d+)",

                "enable_vehicles": r"\bEnableVehicles\s*=\s*(\w+)",
                "car_spawn_rate": r"\bCarSpawnRate\s*=\s*(\d+)",
                "chance_has_gas": r"\bChanceHasGas\s*=\s*(\d+)",
                "initial_gas": r"\bInitialGas\s*=\s*(\d+)",
                "fuel_consumption": r"\bFuelConsumption\s*=\s*([\d\.]+)",
                "car_gas_consumption": r"\bCarGasConsumption\s*=\s*([\d\.]+)",
                "car_alarm_freq": r"\bCarAlarmFrequency\s*=\s*(\d+)",
                "locked_car": r"\bLockedCar\s*=\s*(\d+)",
                "car_condition": r"\bCarGeneralCondition\s*=\s*(\d+)",
                "car_damage_impact": r"\bCarDamageOnImpact\s*=\s*(\d+)",
                "crash_player_damage": r"\bDamageToPlayerFromCarCrash\s*=\s*(\w+)",
                "traffic_jam": r"\bTrafficJam\s*=\s*(\w+)",
                "zombie_attraction_multiplier": r"\bZombieAttractionMultiplier\s*=\s*([\d\.]+)",

                "helicopter": r"\bHelicopter\s*=\s*(\d+)",
                "meta_event": r"\bMetaEvent\s*=\s*(\d+)",
                "sleeping_event": r"\bSleepingEvent\s*=\s*(\d+)",
                "survivor_house_chance": r"\bSurvivorHouseChance\s*=\s*(\d+)",
                "vehicle_story_chance": r"\bVehicleStoryChance\s*=\s*(\d+)",
                "zone_story_chance": r"\bZoneStoryChance\s*=\s*(\d+)",
                "generator_spawning": r"\bGeneratorSpawning\s*=\s*(\d+)",
                "generator_fuel_consumption": r"\bGeneratorFuelConsumption\s*=\s*([\d\.]+)",

                "allow_mini_map": r"Map\s*=\s*\{[^}]*AllowMiniMap\s*=\s*(\w+)",
                "allow_world_map": r"Map\s*=\s*\{[^}]*AllowWorldMap\s*=\s*(\w+)",
                "map_all_known": r"Map\s*=\s*\{[^}]*MapAllKnown\s*=\s*(\w+)",
            }

            for key, pattern in token_map.items():
                m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if m:
                    raw_val = m.group(1).strip()
                    if raw_val.lower() == "true":
                        data[key] = True
                    elif raw_val.lower() == "false":
                        data[key] = False
                    else:
                        try:
                            if "." in raw_val:
                                data[key] = float(raw_val)
                            else:
                                data[key] = int(raw_val)
                        except ValueError:
                            data[key] = raw_val
        except Exception:
            pass

        return data

    def save_sandbox(self, values: Dict[str, Any]) -> bool:
        """Guarda o actualiza las variables en SandboxVars.lua."""
        try:
            self.sandbox_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.sandbox_path.exists():
                content = generate_default_lua(values)
                atomic_write_text(self.sandbox_path, content)
                return True

            text = self.sandbox_path.read_text(encoding="utf-8", errors="replace")

            # Mapa de reemplazo directo sobre el archivo existente
            replace_map = {
                "zombie_speed": ("ZombieLore", "Speed"),
                "zombie_strength": ("ZombieLore", "Strength"),
                "zombie_toughness": ("ZombieLore", "Toughness"),
                "zombie_transmission": ("ZombieLore", "Transmission"),
                "zombie_mortality": ("ZombieLore", "Mortality"),
                "zombie_reanimate": ("ZombieLore", "Reanimate"),
                "zombie_cognition": ("ZombieLore", "Cognition"),
                "zombie_crawl": ("ZombieLore", "CrawlUnderVehicle"),
                "zombie_memory": ("ZombieLore", "Memory"),
                "zombie_decomp": ("ZombieLore", "Decomp"),
                "zombie_sight": ("ZombieLore", "Sight"),
                "zombie_hearing": ("ZombieLore", "Hearing"),
                "zombie_smell": ("ZombieLore", "Smell"),
                "zombie_thump_no_chase": ("ZombieLore", "ThumpNoChasing"),
                "zombie_house_alarm": ("ZombieLore", "TriggerHouseAlarm"),
                "zombie_active_only": ("ZombieLore", "ActiveOnly"),

                "pop_multiplier": ("ZombieConfig", "PopulationMultiplier"),
                "pop_start_multiplier": ("ZombieConfig", "PopulationStartMultiplier"),
                "pop_peak_multiplier": ("ZombieConfig", "PopulationPeakMultiplier"),
                "pop_peak_day": ("ZombieConfig", "PopulationPeakDay"),
                "respawn_multiplier": ("ZombieConfig", "RespawnMultiplier"),
                "respawn_hours": ("ZombieConfig", "RespawnHours"),
                "respawn_unseen_hours": ("ZombieConfig", "RespawnUnseenHours"),
                "redistribute_hours": ("ZombieConfig", "RedistributeHours"),
                "follow_sound_dist": ("ZombieConfig", "FollowSoundDistance"),
                "rally_group_size": ("ZombieConfig", "RallyGroupSize"),

                "day_length": (None, "DayLength"),
                "start_month": (None, "StartMonth"),
                "start_day": (None, "StartDay"),
                "start_time": (None, "StartTime"),
                "water_shut": (None, "WaterShut"),
                "elec_shut": (None, "ElecShut"),
                "water_shut_modifier": (None, "WaterShutModifier"),
                "elec_shut_modifier": (None, "ElecShutModifier"),

                "loot_food": (None, "FoodLoot"),
                "loot_canned_food": (None, "CannedFoodLoot"),
                "loot_literature": (None, "LiteratureLoot"),
                "loot_survival": (None, "SurvivalGearsLoot"),
                "loot_medical": (None, "MedicalLoot"),
                "loot_weapon": (None, "WeaponLoot"),
                "loot_ranged_weapon": (None, "RangedWeaponLoot"),
                "loot_ammo": (None, "AmmoLoot"),
                "loot_mechanics": (None, "MechanicsLoot"),
                "loot_other": (None, "OtherLoot"),

                "temperature": (None, "Temperature"),
                "rain": (None, "Rain"),
                "erosion_speed": (None, "ErosionSpeed"),
                "erosion_days": (None, "ErosionDays"),
                "farming": (None, "Farming"),
                "plant_resilience": (None, "PlantResilience"),
                "plant_abundance": (None, "PlantAbundance"),
                "nature_abundance": (None, "NatureAbundance"),
                "compost_time": (None, "CompostTime"),
                "darkness": (None, "NightDarkness"),
                "fire_spread": (None, "FireSpread"),

                "xp_multiplier": (None, "XPMultiplier"),
                "multi_hit_zombies": (None, "MultiHitZombies"),
                "stats_decrease": (None, "StatsDecrease"),
                "endurance_regen": (None, "EnduranceRegen"),
                "nutrition": (None, "Nutrition"),
                "starter_kit": (None, "StarterKit"),
                "free_trait_points": (None, "CharacterFreePoints"),
                "injury_severity": (None, "InjurySeverity"),
                "bone_fracture": (None, "BoneFracture"),
                "rear_vulnerability": (None, "RearVulnerability"),

                "enable_vehicles": (None, "EnableVehicles"),
                "car_spawn_rate": (None, "CarSpawnRate"),
                "chance_has_gas": (None, "ChanceHasGas"),
                "initial_gas": (None, "InitialGas"),
                "fuel_consumption": (None, "FuelConsumption"),
                "car_gas_consumption": (None, "CarGasConsumption"),
                "car_alarm_freq": (None, "CarAlarmFrequency"),
                "locked_car": (None, "LockedCar"),
                "car_condition": (None, "CarGeneralCondition"),
                "car_damage_impact": (None, "CarDamageOnImpact"),
                "crash_player_damage": (None, "DamageToPlayerFromCarCrash"),
                "traffic_jam": (None, "TrafficJam"),
                "zombie_attraction_multiplier": (None, "ZombieAttractionMultiplier"),

                "helicopter": (None, "Helicopter"),
                "meta_event": (None, "MetaEvent"),
                "sleeping_event": (None, "SleepingEvent"),
                "survivor_house_chance": (None, "SurvivorHouseChance"),
                "vehicle_story_chance": (None, "VehicleStoryChance"),
                "zone_story_chance": (None, "ZoneStoryChance"),
                "generator_spawning": (None, "GeneratorSpawning"),
                "generator_fuel_consumption": (None, "GeneratorFuelConsumption"),

                "allow_mini_map": ("Map", "AllowMiniMap"),
                "allow_world_map": ("Map", "AllowWorldMap"),
                "map_all_known": ("Map", "MapAllKnown"),
            }

            for key, val in values.items():
                if key not in replace_map or val is None:
                    continue
                tbl, token = replace_map[key]
                formatted = _lua_format_val(val)
                if tbl:
                    # Token dentro de una tabla (ej. ZombieLore = { ... Speed = 2 ... })
                    pat = re.compile(rf"({tbl}\s*=\s*\{{[^}}]*\b{token}\s*=\s*)[^,}}\n]+", re.DOTALL)
                    if pat.search(text):
                        text = pat.sub(rf"\g<1>{formatted}", text)
                else:
                    # Token plano (ej. DayLength = 2,)
                    pat = re.compile(rf"(\b{token}\s*=\s*)[^,}}\n]+")
                    if pat.search(text):
                        text = pat.sub(rf"\g<1>{formatted}", text)

            atomic_write_text(self.sandbox_path, text)
            return True
        except Exception:
            return False

    def get_raw_sandbox(self) -> str:
        if self.sandbox_path.exists():
            try:
                return self.sandbox_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        return generate_default_lua(DEFAULT_SANDBOX_SETTINGS)

    def save_raw_sandbox(self, content: str) -> bool:
        try:
            self.sandbox_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.sandbox_path, content)
            activity_manager.log("Configuración", "Archivo SandboxVars.lua actualizado directamente")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------- Mods
    def get_mods(self) -> Dict[str, Any]:
        ini = self.read_ini()
        workshop = ini.get("WorkshopItems", "")
        mods_raw = ini.get("Mods", workshop)
        items = [m.strip() for m in re.split(r"[;,]", workshop) if m.strip()]
        return {
            "mod_ids_raw": workshop,
            "mods": items,
            "mods_names_raw": mods_raw,
            "count": len(items),
        }

    def save_mods(self, mod_ids_raw: str, mods_names_raw: Optional[str] = None) -> Dict[str, Any]:
        workshop_tokens = [m.strip() for m in re.split(r"[;,]", mod_ids_raw) if m.strip()]
        clean_workshop = ";".join(workshop_tokens)

        updates = {"WorkshopItems": clean_workshop}
        if mods_names_raw is not None:
            mod_tokens = [m.strip() for m in re.split(r"[;,]", mods_names_raw) if m.strip()]
            updates["Mods"] = ";".join(mod_tokens)
        else:
            updates["Mods"] = clean_workshop

        ok = self.set_ini_values(updates)
        if ok:
            activity_manager.log("Mods", f"Lista de mods actualizada ({len(workshop_tokens)} items)")
        return {"success": ok, "mod_ids": clean_workshop, "count": len(workshop_tokens)}

    # ------------------------------------------------------------- Resumen Completo
    def get_all_settings(self) -> Dict[str, Any]:
        return {
            "server_name": settings.server_name,
            "server": self.read_ini(),
            "sandbox": self.read_sandbox(),
            "panel": {
                "server_name": settings.server_name,
                "memory_min": settings.memory_min,
                "memory_max": settings.memory_max,
                "use_steam": settings.use_steam,
                "autostart_server": settings.autostart_server,
                "update_on_start": settings.update_on_start,
                "branch": settings.branch,
                "additional_args": settings.additional_args,
                "server_port": settings.server_port,
                "direct_port": settings.direct_port,
            },
            "raw_ini": self.get_raw_ini(),
            "raw_sandbox": self.get_raw_sandbox(),
        }

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        server_vals = payload.get("server") or {}
        sandbox_vals = payload.get("sandbox") or {}
        panel_vals = payload.get("panel") or {}

        # 1. Guardar variables de runtime/panel
        if panel_vals:
            panel_updates = {}
            if "memory_min" in panel_vals:
                panel_updates["memory_min"] = str(panel_vals["memory_min"]).strip()
            if "memory_max" in panel_vals:
                panel_updates["memory_max"] = str(panel_vals["memory_max"]).strip()
            if "use_steam" in panel_vals:
                panel_updates["use_steam"] = str(panel_vals["use_steam"]).lower() in ("true", "1", "yes", "on")
            if "autostart_server" in panel_vals:
                panel_updates["autostart_server"] = str(panel_vals["autostart_server"]).lower() in ("true", "1", "yes", "on")
            if "update_on_start" in panel_vals:
                panel_updates["update_on_start"] = str(panel_vals["update_on_start"]).lower() in ("true", "1", "yes", "on")
            if "branch" in panel_vals:
                panel_updates["branch"] = str(panel_vals["branch"]).strip()
            if "additional_args" in panel_vals:
                panel_updates["additional_args"] = str(panel_vals["additional_args"]).strip()
            if panel_updates:
                settings.save_runtime_config(panel_updates)

        # 2. Guardar variables en .ini
        ini_ok = True
        if server_vals:
            ini_ok = self.set_ini_values(server_vals)

        # 3. Guardar variables en SandboxVars.lua
        sandbox_ok = True
        if sandbox_vals:
            sandbox_ok = self.save_sandbox(sandbox_vals)

        activity_manager.log("Configuración", "Ajustes de servidor y sandbox guardados")
        return {
            "success": ini_ok and sandbox_ok,
            "ini_saved": ini_ok,
            "sandbox_saved": sandbox_ok,
        }


pz_settings_manager = PzSettingsManager()
