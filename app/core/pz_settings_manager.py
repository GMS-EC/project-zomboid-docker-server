import re
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

import httpx

from app.config import settings
from app.core.fs_utils import atomic_write_text, atomic_write_json
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
    "zombie_speed": 2,
    "zombie_strength": 2,
    "zombie_toughness": 2,
    "zombie_transmission": 1,
    "zombie_mortality": 5,
    "zombie_reanimate": 3,
    "zombie_cognition": 3,
    "zombie_crawl": 5,
    "zombie_memory": 2,
    "zombie_decomp": 1,
    "zombie_sight": 2,
    "zombie_hearing": 2,
    "zombie_smell": 2,
    "zombie_thump_no_chase": False,
    "zombie_house_alarm": False,
    "zombie_active_only": 1,

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
    "day_length": 2,
    "start_month": 7,
    "start_day": 9,
    "start_time": 2,
    "water_shut": 2,
    "elec_shut": 2,
    "water_shut_modifier": 14,
    "elec_shut_modifier": 14,
    "temperature": 3,
    "rain": 3,
    "erosion_speed": 3,
    "erosion_days": 100,
    "farming": 3,
    "plant_resilience": 3,
    "plant_abundance": 3,
    "nature_abundance": 3,
    "compost_time": 2,
    "darkness": 3,
    "fire_spread": True,

    # Botín
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
    "multi_hit_zombies": True,
    "stats_decrease": 3,
    "endurance_regen": 3,
    "nutrition": True,
    "starter_kit": False,
    "free_trait_points": 0,
    "injury_severity": 2,
    "bone_fracture": True,
    "rear_vulnerability": 2,

    # Vehículos
    "enable_vehicles": True,
    "car_spawn_rate": 3,
    "chance_has_gas": 2,
    "initial_gas": 2,
    "fuel_consumption": 1.0,
    "car_gas_consumption": 1.0,
    "car_alarm_freq": 2,
    "locked_car": 3,
    "car_condition": 2,
    "car_damage_impact": 3,
    "crash_player_damage": True,
    "traffic_jam": True,
    "zombie_attraction_multiplier": 1.0,

    # Meta-Eventos, Historias y Generadores
    "helicopter": 2,
    "meta_event": 2,
    "sleeping_event": 2,
    "survivor_house_chance": 3,
    "vehicle_story_chance": 3,
    "zone_story_chance": 3,
    "generator_spawning": 3,
    "generator_fuel_consumption": 1.0,

    # Mapa en el Juego
    "allow_mini_map": True,
    "allow_world_map": True,
    "map_all_known": False,
}

_BBCODE_RE = re.compile(r"\[/?[a-zA-Z0-9*=]+[^\]]*\]")
_MOD_ID_LINE_RE = re.compile(r"(?:^|[\r\n])\s*Mod\s*IDs?\s*[:=]\s*([^\r\n]+)", re.IGNORECASE)
_MAP_FOLDER_LINE_RE = re.compile(r"(?:^|[\r\n])\s*Map\s*(?:Folder|Name)?s?\s*[:=]\s*([^\r\n]+)", re.IGNORECASE)


def _dedup_preserve(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        clean = item.strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


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
    """Gestor de configuración de PZ (<SERVER_NAME>.ini, SandboxVars.lua, spawnregions y mods)."""

    @property
    def ini_path(self) -> Path:
        return settings.data_dir / "Server" / f"{settings.server_name}.ini"

    @property
    def sandbox_path(self) -> Path:
        return settings.data_dir / "Server" / f"{settings.server_name}_SandboxVars.lua"

    @property
    def spawnregions_path(self) -> Path:
        return settings.data_dir / "Server" / f"{settings.server_name}_spawnregions.lua"

    @property
    def mods_catalog_path(self) -> Path:
        return settings.panel_dir / "mods_catalog.json"

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
        try:
            self.sandbox_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.sandbox_path.exists():
                content = generate_default_lua(values)
                atomic_write_text(self.sandbox_path, content)
                return True

            text = self.sandbox_path.read_text(encoding="utf-8", errors="replace")
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
                    pat = re.compile(rf"({tbl}\s*=\s*\{{[^}}]*\b{token}\s*=\s*)[^,}}\n]+", re.DOTALL)
                    if pat.search(text):
                        text = pat.sub(rf"\g<1>{formatted}", text)
                else:
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

    # ------------------------------------------------------------- SpawnRegions & Perfiles
    VANILLA_SPAWN_REGIONS = (
        "Muldraugh, KY",
        "Riverside, KY",
        "Rosewood, KY",
        "West Point, KY",
    )

    def _default_spawnregions_lua(self, custom_maps: Optional[List[str]] = None) -> str:
        vanilla_low = {v.lower() for v in self.VANILLA_SPAWN_REGIONS}
        lines = ["function SpawnRegions()", "\treturn {"]
        seen = set()
        for m in (custom_maps or []):
            clean = str(m or "").replace('"', "").replace("\n", "").replace("\r", "").strip()
            if not clean or clean.lower() in vanilla_low or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            lines.append(f'\t\t{{ name = "{clean}", file = "media/maps/{clean}/spawnpoints.lua" }},')
        for v in self.VANILLA_SPAWN_REGIONS:
            lines.append(f'\t\t{{ name = "{v}", file = "media/maps/{v}/spawnpoints.lua" }},')
        lines.extend(["\t}", "end", ""])
        return "\n".join(lines)

    def get_raw_spawnregions(self) -> str:
        if self.spawnregions_path.exists():
            try:
                return self.spawnregions_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        return self._default_spawnregions_lua()

    def save_raw_spawnregions(self, content: str) -> bool:
        try:
            self.spawnregions_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.spawnregions_path, content)
            activity_manager.log("Configuración", "Archivo spawnregions.lua actualizado directamente")
            return True
        except Exception:
            return False

    def sync_spawnregions(self, map_folders: List[str]) -> bool:
        """Sincroniza mapas personalizados en <SERVER_NAME>_spawnregions.lua antes de Muldraugh."""
        try:
            vanilla_low = {v.lower() for v in self.VANILLA_SPAWN_REGIONS}
            preserved_lines: List[str] = []
            seen = set()
            if self.spawnregions_path.exists():
                for raw in self.spawnregions_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    m_name = re.search(r'\{\s*name\s*=\s*"([^"]+)"', raw)
                    if m_name:
                        rname = m_name.group(1).strip()
                        if rname.lower() not in vanilla_low and rname.lower() not in seen:
                            seen.add(rname.lower())
                            preserved_lines.append("\t\t" + raw.strip().rstrip(",") + ",")

            for m in (map_folders or []):
                clean = str(m or "").replace('"', "").replace("\n", "").replace("\r", "").strip()
                if not clean or clean.lower() in vanilla_low or clean.lower() in seen:
                    continue
                seen.add(clean.lower())
                preserved_lines.append(f'\t\t{{ name = "{clean}", file = "media/maps/{clean}/spawnpoints.lua" }},')

            lines = ["function SpawnRegions()", "\treturn {"]
            lines.extend(preserved_lines)
            for v in self.VANILLA_SPAWN_REGIONS:
                lines.append(f'\t\t{{ name = "{v}", file = "media/maps/{v}/spawnpoints.lua" }},')
            lines.extend(["\t}", "end", ""])

            self.spawnregions_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.spawnregions_path, "\n".join(lines))
            return True
        except Exception:
            return False

    def list_profiles(self) -> List[str]:
        server_dir = settings.data_dir / "Server"
        profiles: List[str] = [settings.server_name]
        if server_dir.is_dir():
            for f in sorted(server_dir.glob("*.ini")):
                if f.is_file() and f.stem and f.stem not in profiles:
                    profiles.append(f.stem)
        return profiles

    # ------------------------------------------------------------- Mods Inteligentes PZ
    def _load_mods_catalog(self) -> Dict[str, Any]:
        if not self.mods_catalog_path.exists():
            return {}
        try:
            data = json.loads(self.mods_catalog_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_mods_catalog(self, catalog: Dict[str, Any]) -> None:
        try:
            atomic_write_json(self.mods_catalog_path, catalog, indent=2)
        except Exception:
            pass

    @staticmethod
    def _parse_mod_info(mod_info_file: Path) -> Dict[str, Any]:
        info: Dict[str, Any] = {"name": "", "id": "", "description": "", "require": "", "maps": []}
        try:
            for raw in mod_info_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                key = k.strip().lower()
                val = v.strip()
                if key in ("name", "id", "description", "require", "modversion"):
                    info[key] = val
        except Exception:
            pass

        # Detectar carpetas de mapas dentro de media/maps/
        maps_dir = mod_info_file.parent / "media" / "maps"
        if maps_dir.is_dir():
            for child in sorted(maps_dir.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    info["maps"].append(child.name)
        return info

    def scan_local_mods(self) -> Dict[str, Any]:
        """Escanea mod.info locales en Workshop (108600) y carpetas mods/."""
        by_workshop: Dict[str, Dict[str, Any]] = {}
        by_mod_id: Dict[str, Dict[str, Any]] = {}

        workshop_roots = [
            settings.server_dir / "steamapps" / "workshop" / "content" / "108600",
            settings.data_dir / "Workshop" / "steamapps" / "workshop" / "content" / "108600",
        ]
        for wroot in workshop_roots:
            if not wroot.is_dir():
                continue
            for wid_dir in wroot.iterdir():
                if not wid_dir.is_dir() or not wid_dir.name.isdigit():
                    continue
                wid = wid_dir.name
                mod_ids: List[str] = []
                map_folders: List[str] = []
                titles: List[str] = []
                for mod_info in wid_dir.rglob("mod.info"):
                    parsed = self._parse_mod_info(mod_info)
                    if parsed["id"]:
                        mod_ids.append(parsed["id"])
                    if parsed["name"]:
                        titles.append(parsed["name"])
                    map_folders.extend(parsed["maps"])
                entry = {
                    "workshop_id": wid,
                    "title": titles[0] if titles else "",
                    "mod_ids": _dedup_preserve(mod_ids),
                    "map_folders": _dedup_preserve(map_folders),
                    "installed_locally": True,
                    "source": "mod.info",
                }
                by_workshop[wid] = entry
                for mid in entry["mod_ids"]:
                    by_mod_id[mid] = {
                        "mod_id": mid,
                        "name": entry["title"] or mid,
                        "workshop_id": wid,
                        "map_folders": entry["map_folders"],
                        "installed_locally": True,
                    }

        # Mods sueltos (No-Steam / manuales) en data_dir/mods
        local_mods_dir = settings.data_dir / "mods"
        if local_mods_dir.is_dir():
            for mod_info in local_mods_dir.rglob("mod.info"):
                parsed = self._parse_mod_info(mod_info)
                mid = parsed.get("id")
                if mid and mid not in by_mod_id:
                    by_mod_id[mid] = {
                        "mod_id": mid,
                        "name": parsed.get("name") or mid,
                        "workshop_id": "",
                        "map_folders": _dedup_preserve(parsed.get("maps", [])),
                        "installed_locally": True,
                    }

        if by_workshop:
            catalog = self._load_mods_catalog()
            for wid, info in by_workshop.items():
                prev = catalog.get(wid, {})
                merged = {
                    **prev,
                    **{k: v for k, v in info.items() if v},
                    "mod_ids": info["mod_ids"] or prev.get("mod_ids", []),
                    "map_folders": info["map_folders"] or prev.get("map_folders", []),
                    "installed_locally": True,
                }
                catalog[wid] = merged
            self._save_mods_catalog(catalog)

        return {"by_workshop": by_workshop, "by_mod_id": by_mod_id}

    @staticmethod
    def _extract_ids_from_steam_description(desc: str) -> Dict[str, List[str]]:
        if not desc:
            return {"mod_ids": [], "map_folders": []}
        clean = _BBCODE_RE.sub("", desc)
        mod_ids: List[str] = []
        map_folders: List[str] = []

        for m in _MOD_ID_LINE_RE.finditer(clean):
            raw = m.group(1).strip()
            for part in re.split(r"[;,/]", raw):
                tok = part.strip().strip("`\"' ")
                if tok and " " not in tok and len(tok) <= 64 and tok.lower() not in ("workshop", "id"):
                    mod_ids.append(tok)

        for m in _MAP_FOLDER_LINE_RE.finditer(clean):
            raw = m.group(1).strip()
            for part in re.split(r"[;/]", raw):
                tok = part.strip().strip("`\"' ")
                if tok and len(tok) <= 64 and not tok.lower().startswith("http"):
                    map_folders.append(tok)

        return {
            "mod_ids": _dedup_preserve(mod_ids),
            "map_folders": _dedup_preserve(map_folders),
        }

    async def resolve_workshop_items(
        self,
        workshop_ids: List[str],
        sync_to_ini: bool = False,
    ) -> Dict[str, Any]:
        """Consulta la API pública de Steam Workshop y fusiona con mod.info local."""
        clean_ids = _dedup_preserve([str(w).strip() for w in workshop_ids if str(w).strip().isdigit()])
        local = self.scan_local_mods()["by_workshop"]
        catalog = self._load_mods_catalog()
        resolved: Dict[str, Any] = {}

        if clean_ids:
            form_data: Dict[str, str] = {"itemcount": str(len(clean_ids))}
            for idx, wid in enumerate(clean_ids):
                form_data[f"publishedfileids[{idx}]"] = wid

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                        data=form_data,
                    )
                if resp.status_code == 200:
                    details = resp.json().get("response", {}).get("publishedfiledetails", [])
                    for item in details:
                        wid = str(item.get("publishedfileid", "")).strip()
                        if not wid:
                            continue
                        desc = item.get("description", "") or ""
                        parsed = self._extract_ids_from_steam_description(desc)
                        loc = local.get(wid, {})
                        prev = catalog.get(wid, {})
                        entry = {
                            "workshop_id": wid,
                            "title": item.get("title") or loc.get("title") or prev.get("title") or f"Workshop {wid}",
                            "preview_url": item.get("preview_url") or prev.get("preview_url") or "",
                            "file_size": int(item.get("file_size") or 0),
                            "time_updated": int(item.get("time_updated") or 0),
                            "mod_ids": loc.get("mod_ids") or parsed["mod_ids"] or prev.get("mod_ids", []),
                            "map_folders": loc.get("map_folders") or parsed["map_folders"] or prev.get("map_folders", []),
                            "installed_locally": bool(loc),
                            "source": "mod.info + steam" if loc else "steam_api",
                        }
                        catalog[wid] = entry
                        resolved[wid] = entry
            except Exception:
                pass

        # Fallback para los que no respondieron por Steam (ej. offline) pero sí están en local/catálogo
        for wid in clean_ids:
            if wid not in resolved:
                loc = local.get(wid)
                prev = catalog.get(wid)
                if loc:
                    catalog[wid] = {**(prev or {}), **loc}
                    resolved[wid] = catalog[wid]
                elif prev:
                    resolved[wid] = prev

        self._save_mods_catalog(catalog)

        if sync_to_ini and clean_ids:
            ini = self.read_ini()
            existing_mods = [m.strip() for m in re.split(r"[;,]", ini.get("Mods", "")) if m.strip()]
            # Quitar placeholders numéricos que coincidan con workshop_ids ya resueltos
            resolved_wids = {wid for wid, info in resolved.items() if info.get("mod_ids")}
            cleaned_mods = [m for m in existing_mods if m not in resolved_wids]
            existing_maps = [m.strip() for m in re.split(r"[;]", ini.get("Map", "Muldraugh, KY")) if m.strip()]
            for wid in clean_ids:
                info = resolved.get(wid, {})
                for mid in info.get("mod_ids", []):
                    if mid not in cleaned_mods:
                        cleaned_mods.append(mid)
                for mf in info.get("map_folders", []):
                    if mf not in existing_maps:
                        if "Muldraugh, KY" in existing_maps:
                            existing_maps.insert(existing_maps.index("Muldraugh, KY"), mf)
                        else:
                            existing_maps.insert(0, mf)
            self.set_ini_values({"Mods": ";".join(cleaned_mods), "Map": ";".join(existing_maps or ["Muldraugh, KY"])})
            self.sync_spawnregions(existing_maps)

        return {"success": True, "resolved": resolved, "count": len(resolved)}

    async def resolve_workshop_collection(self, collection_input: str) -> Dict[str, Any]:
        """Importa todos los mods de una Colección pública de Steam Workshop."""
        raw = str(collection_input or "").strip()
        m_url = re.search(r"[?&]id=(\d+)", raw)
        m_num = re.search(r"(\d+)", raw)
        clean_cid = m_url.group(1) if m_url else (m_num.group(1) if m_num else "")
        if not clean_cid:
            return {"success": False, "error": "ID o URL de colección no válido."}

        child_ids: List[str] = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/",
                    data={"collectioncount": "1", "publishedfileids[0]": clean_cid},
                )
            if resp.status_code != 200:
                return {"success": False, "error": f"Steam API devolvió HTTP {resp.status_code}."}
            details = resp.json().get("response", {}).get("collectiondetails", [])
            if not details or details[0].get("result") != 1:
                return {"success": False, "error": "Colección no encontrada o privada en Steam Workshop."}
            for child in details[0].get("children", []):
                cid = str(child.get("publishedfileid", "")).strip()
                if cid.isdigit():
                    child_ids.append(cid)
        except Exception as e:
            return {"success": False, "error": f"Error consultando Steam Workshop: {e}"}

        child_ids = _dedup_preserve(child_ids)
        if not child_ids:
            return {"success": False, "error": "La colección no contiene elementos de Workshop."}

        res_items = await self.resolve_workshop_items(child_ids, sync_to_ini=False)
        resolved = res_items.get("resolved", {})

        current = self.get_mods()
        merged_workshop = _dedup_preserve(current["workshop_items"] + child_ids)
        merged_mod_ids = list(current["mod_ids"])
        merged_maps = list(current["map_folders"] or ["Muldraugh, KY"])

        for wid in child_ids:
            info = resolved.get(wid, {})
            for mid in info.get("mod_ids", []):
                if mid not in merged_mod_ids:
                    merged_mod_ids.append(mid)
            for mf in info.get("map_folders", []):
                if mf not in merged_maps:
                    if "Muldraugh, KY" in merged_maps:
                        merged_maps.insert(merged_maps.index("Muldraugh, KY"), mf)
                    else:
                        merged_maps.insert(0, mf)

        self.save_mods(
            ";".join(merged_workshop),
            mods_names_raw=";".join(merged_mod_ids),
            map_raw=";".join(merged_maps),
        )
        activity_manager.log(
            "Mods",
            f"Colección Steam #{clean_cid} importada ({len(child_ids)} ítems)",
            action="mods_collection_import",
        )
        return {
            "success": True,
            "collection_id": clean_cid,
            "imported_count": len(child_ids),
            "workshop_items": merged_workshop,
            "mod_ids": merged_mod_ids,
            "map_folders": merged_maps,
        }

    def get_mods(self) -> Dict[str, Any]:
        ini = self.read_ini()
        workshop_raw = ini.get("WorkshopItems", "")
        mods_raw = ini.get("Mods", "")
        map_raw = ini.get("Map", "Muldraugh, KY")

        workshop_items = _dedup_preserve([m.strip() for m in re.split(r"[;,]", workshop_raw) if m.strip()])
        mod_ids = _dedup_preserve([m.strip() for m in re.split(r"[;,]", mods_raw) if m.strip()])
        map_folders = _dedup_preserve([m.strip() for m in re.split(r"[;]", map_raw) if m.strip()])

        local_scan = self.scan_local_mods()
        catalog = self._load_mods_catalog()
        mod_ids_set = set(mod_ids)

        catalog_entries: List[Dict[str, Any]] = []
        accounted_mod_ids = set()
        for wid in workshop_items:
            info = catalog.get(wid) or local_scan["by_workshop"].get(wid) or {}
            known_mids = list(info.get("mod_ids") or [])
            active_mids = [m for m in known_mids if m in mod_ids_set]
            accounted_mod_ids.update(active_mids)
            catalog_entries.append({
                "workshop_id": wid,
                "title": info.get("title") or f"Workshop #{wid}",
                "mod_ids": known_mids,
                "active_mod_ids": active_mids,
                "map_folders": list(info.get("map_folders") or []),
                "preview_url": info.get("preview_url") or "",
                "installed_locally": bool(local_scan["by_workshop"].get(wid)),
                "source": info.get("source") or "manual",
            })

        standalone_mods = [m for m in mod_ids if m not in accounted_mod_ids]

        return {
            "steam_mode": settings.use_steam,
            "workshop_items": workshop_items,
            "workshop_items_raw": ";".join(workshop_items),
            "mod_ids": mod_ids,
            "mods_names_raw": ";".join(mod_ids),
            "map_folders": map_folders,
            "map_raw": ";".join(map_folders),
            "mod_ids_raw": ";".join(workshop_items),
            "mods": workshop_items,
            "count": len(workshop_items) if workshop_items else len(mod_ids),
            "catalog": catalog_entries,
            "standalone_mods": standalone_mods,
            "local_mods": list(local_scan["by_mod_id"].values()),
        }

    def save_mods(
        self,
        workshop_items_raw: str,
        mods_names_raw: Optional[str] = None,
        map_raw: Optional[str] = None,
        catalog_hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Guarda WorkshopItems= y Mods= manteniéndolos correctamente separados."""
        ini = self.read_ini()
        old_workshop = _dedup_preserve([m.strip() for m in re.split(r"[;,]", ini.get("WorkshopItems", "")) if m.strip()])
        old_mods = _dedup_preserve([m.strip() for m in re.split(r"[;,]", ini.get("Mods", "")) if m.strip()])

        workshop_tokens = _dedup_preserve([m.strip() for m in re.split(r"[;,]", workshop_items_raw or "") if m.strip()])
        clean_workshop = ";".join(workshop_tokens)

        catalog = self._load_mods_catalog()
        if catalog_hints:
            for wid, hint in catalog_hints.items():
                if not wid or not isinstance(hint, dict):
                    continue
                prev = catalog.get(wid, {})
                merged_mids = _dedup_preserve([str(x) for x in (hint.get("mod_ids") or []) if str(x).strip()])
                merged_maps = _dedup_preserve([str(x) for x in (hint.get("map_folders") or []) if str(x).strip()])
                catalog[wid] = {
                    **prev,
                    "workshop_id": wid,
                    "title": hint.get("title") or prev.get("title") or f"Workshop #{wid}",
                    "mod_ids": merged_mids or prev.get("mod_ids", []),
                    "map_folders": merged_maps or prev.get("map_folders", []),
                    "preview_url": hint.get("preview_url") or prev.get("preview_url", ""),
                    "source": hint.get("source") or prev.get("source") or "manual",
                }
            self._save_mods_catalog(catalog)

        if mods_names_raw is not None:
            mod_tokens = _dedup_preserve([m.strip() for m in re.split(r"[;,]", mods_names_raw) if m.strip()])
        else:
            removed_wids = set(old_workshop) - set(workshop_tokens)
            removed_mids = set(removed_wids)
            for rwid in removed_wids:
                for mid in catalog.get(rwid, {}).get("mod_ids", []):
                    removed_mids.add(mid)

            mod_tokens = [m for m in old_mods if m not in removed_mids]
            for wid in workshop_tokens:
                for mid in catalog.get(wid, {}).get("mod_ids", []):
                    if mid not in mod_tokens:
                        mod_tokens.append(mid)

        clean_mods = ";".join(mod_tokens)
        updates: Dict[str, str] = {
            "WorkshopItems": clean_workshop,
            "Mods": clean_mods,
        }
        if map_raw is not None:
            map_tokens = _dedup_preserve([m.strip() for m in re.split(r"[;]", map_raw) if m.strip()])
            updates["Map"] = ";".join(map_tokens) if map_tokens else "Muldraugh, KY"

        ok = self.set_ini_values(updates)
        if ok:
            if map_raw is not None:
                self.sync_spawnregions(map_tokens)
            activity_manager.log(
                "Mods",
                f"Mods actualizados: {len(workshop_tokens)} WorkshopItems / {len(mod_tokens)} ModIDs",
            )
        return {
            "success": ok,
            "workshop_items": clean_workshop,
            "mod_ids": clean_mods,
            "count": len(workshop_tokens) if workshop_tokens else len(mod_tokens),
        }

    # ------------------------------------------------------------- Resumen Completo
    def get_all_settings(self) -> Dict[str, Any]:
        return {
            "server_name": settings.server_name,
            "profiles": self.list_profiles(),
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
                "rcon_port": settings.rcon_port,
                "public_address": settings.public_address,
                "disk_limit_gb": settings.disk_limit_gb,
            },
            "raw_ini": self.get_raw_ini(),
            "raw_sandbox": self.get_raw_sandbox(),
            "raw_spawnregions": self.get_raw_spawnregions(),
        }

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        server_vals = payload.get("server") or {}
        sandbox_vals = payload.get("sandbox") or {}
        panel_vals = payload.get("panel") or {}

        panel_updates: Dict[str, Any] = {}
        if panel_vals:
            if "server_name" in panel_vals and str(panel_vals["server_name"] or "").strip():
                clean_sname = "".join(
                    c for c in str(panel_vals["server_name"]).strip()
                    if c.isalnum() or c in ("_", "-")
                )
                if clean_sname:
                    panel_updates["server_name"] = clean_sname
            if "memory_min" in panel_vals and str(panel_vals["memory_min"]).strip():
                panel_updates["memory_min"] = str(panel_vals["memory_min"]).strip()
            if "memory_max" in panel_vals and str(panel_vals["memory_max"]).strip():
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
            if "public_address" in panel_vals:
                panel_updates["public_address"] = str(panel_vals["public_address"] or "").strip()
            if "disk_limit_gb" in panel_vals:
                try:
                    panel_updates["disk_limit_gb"] = max(0.0, float(panel_vals["disk_limit_gb"] or 0))
                except (TypeError, ValueError):
                    pass

        # Sincronizar campos clave del .ini al runtime_config para el banner/panel
        if server_vals:
            if "MaxPlayers" in server_vals:
                try:
                    panel_updates["max_players"] = max(1, int(server_vals["MaxPlayers"]))
                except (TypeError, ValueError):
                    pass
            if "DefaultPort" in server_vals:
                try:
                    panel_updates["server_port"] = int(server_vals["DefaultPort"])
                except (TypeError, ValueError):
                    pass
            if "UDPPort" in server_vals:
                try:
                    panel_updates["direct_port"] = int(server_vals["UDPPort"])
                except (TypeError, ValueError):
                    pass
            if "RCONPort" in server_vals:
                try:
                    panel_updates["rcon_port"] = int(server_vals["RCONPort"])
                except (TypeError, ValueError):
                    pass
            if "RCONPassword" in server_vals:
                panel_updates["rcon_password"] = str(server_vals["RCONPassword"])

        if panel_updates:
            settings.save_runtime_config(panel_updates)

        if not settings.use_steam:
            server_vals = dict(server_vals)
            server_vals["WorkshopItems"] = ""
            server_vals["Mods"] = ""
            server_vals["Public"] = "false"
            server_vals["SteamVAC"] = "false"
            server_vals["SteamScoreboard"] = "false"

        ini_ok = True
        if server_vals:
            ini_ok = self.set_ini_values(server_vals)

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
