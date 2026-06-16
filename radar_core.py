# -*- coding: utf-8 -*-
"""
radar_core.py
=============
Núcleo de cálculo do rastreador de aeronaves.

Pega a posição geodésica de uma aeronave (latitude, longitude, altitude WGS84)
e a converte para COORDENADAS POLARES TOPOCÊNTRICAS (azimute, elevação e
distância oblíqua / slant range) em relação a um radar de origem.

Cadeia de transformação:
    Geodésica (lat, lon, h)  ->  ECEF (X, Y, Z)  ->  ENU (Leste, Norte, Cima)
                             ->  Polar local (azimute, elevação, distância)

Modelo da Terra: elipsoide WGS84.
Sem dependências externas (apenas a biblioteca padrão), para rodar em qualquer
máquina e ser fácil de empacotar para Android (Kivy/BeeWare).
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constantes do elipsoide WGS84
# ---------------------------------------------------------------------------
WGS84_A = 6_378_137.0                 # semi-eixo maior (m)
WGS84_F = 1.0 / 298.257223563         # achatamento
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)  # 1ª excentricidade ao quadrado (e^2)
FT_TO_M = 0.3048                      # pés -> metros (altitude do FlightRadar24)


@dataclass(frozen=True)
class RadarSite:
    """Sensor de rastreio. As coordenadas ECEF da origem são pré-calculadas
    uma única vez (eficiência: não recalcula a cada aeronave)."""
    nome: str
    lat: float          # graus decimais
    lon: float          # graus decimais
    h: float            # altura geodésica em metros
    _ecef: tuple = field(default=None, repr=False, compare=False)

    @classmethod
    def criar(cls, nome: str, lat: float, lon: float, h: float) -> "RadarSite":
        site = cls(nome=nome, lat=lat, lon=lon, h=h)
        object.__setattr__(site, "_ecef", geodetic_to_ecef(lat, lon, h))
        return site

    @property
    def ecef(self) -> tuple:
        return self._ecef


# ---------------------------------------------------------------------------
# Conversão de DMS (graus, minutos, segundos) -> graus decimais
# ---------------------------------------------------------------------------
def dms_to_deg(graus: float, minutos: float, segundos: float) -> float:
    """Converte 'GG MM SS.sss' em graus decimais.
    O sinal de `graus` (negativo) é propagado (hemisfério Sul/Oeste)."""
    sinal = -1.0 if graus < 0 or (graus == 0 and (minutos < 0 or segundos < 0)) else 1.0
    return sinal * (abs(graus) + abs(minutos) / 60.0 + abs(segundos) / 3600.0)


# ---------------------------------------------------------------------------
# Geodésica -> ECEF (Earth-Centered, Earth-Fixed)
# ---------------------------------------------------------------------------
def geodetic_to_ecef(lat_deg: float, lon_deg: float, h: float) -> tuple:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)  # raio de curvatura 1º vertical
    cos_lat = math.cos(lat)
    X = (N + h) * cos_lat * math.cos(lon)
    Y = (N + h) * cos_lat * math.sin(lon)
    Z = (N * (1.0 - WGS84_E2) + h) * sin_lat
    return (X, Y, Z)


# ---------------------------------------------------------------------------
# ECEF -> ENU (sistema local Leste-Norte-Cima, origem no radar)
# ---------------------------------------------------------------------------
def ecef_to_enu(X, Y, Z, radar: RadarSite) -> tuple:
    X0, Y0, Z0 = radar.ecef
    lat = math.radians(radar.lat)
    lon = math.radians(radar.lon)
    sp, cp = math.sin(lat), math.cos(lat)
    sl, cl = math.sin(lon), math.cos(lon)
    dX, dY, dZ = X - X0, Y - Y0, Z - Z0
    east  = -sl * dX + cl * dY
    north = -sp * cl * dX - sp * sl * dY + cp * dZ
    up    =  cp * cl * dX + cp * sl * dY + sp * dZ
    return (east, north, up)


# ---------------------------------------------------------------------------
# Geodésica -> Polar (Azimute, Elevação, Distância) relativo a um radar
# ---------------------------------------------------------------------------
@dataclass
class Polar:
    azimute: float      # graus, 0..360 (0 = Norte, 90 = Leste)
    elevacao: float     # graus, ângulo acima do horizonte local
    distancia: float    # metros, distância oblíqua (slant range)
    east: float = 0.0
    north: float = 0.0
    up: float = 0.0


def geodetic_to_polar(lat_av: float, lon_av: float, h_av: float,
                      radar: RadarSite) -> Polar:
    """Núcleo do rastreio. Usa atan2 e norma euclidiana — ROBUSTO em todos os
    quadrantes e nas geometrias singulares (aeronave a Norte/Sul exato ou no
    horizonte), onde as fórmulas originais do APK falhavam."""
    X, Y, Z = geodetic_to_ecef(lat_av, lon_av, h_av)
    east, north, up = ecef_to_enu(X, Y, Z, radar)

    horizontal = math.hypot(east, north)
    azimute = math.degrees(math.atan2(east, north)) % 360.0
    elevacao = math.degrees(math.atan2(up, horizontal))
    distancia = math.sqrt(east * east + north * north + up * up)
    return Polar(azimute, elevacao, distancia, east, north, up)


# ---------------------------------------------------------------------------
# Predição (navegação estimada) e taxa de variação
# ---------------------------------------------------------------------------
def prever_posicao(lat_deg: float, lon_deg: float, track_deg: float,
                   gspeed_kt: float, dt_s: float) -> tuple:
    """Estima a posição (lat, lon) `dt_s` segundos à frente, seguindo a proa
    (track) e a velocidade no solo (nós), por navegação estimada sobre a
    esfera. Altitude considerada constante no curto prazo."""
    d = gspeed_kt * 0.514444 * dt_s          # distância percorrida (m)
    if d <= 0:
        return lat_deg, lon_deg
    R = 6_371_000.0
    ang = math.radians(track_deg)
    delta = d / R
    f1 = math.radians(lat_deg)
    l1 = math.radians(lon_deg)
    f2 = math.asin(math.sin(f1) * math.cos(delta)
                   + math.cos(f1) * math.sin(delta) * math.cos(ang))
    l2 = l1 + math.atan2(math.sin(ang) * math.sin(delta) * math.cos(f1),
                         math.cos(delta) - math.sin(f1) * math.sin(f2))
    return math.degrees(f2), math.degrees(l2)


def taxa_aproximacao(lat, lon, h, track_deg, gspeed_kt, radar: RadarSite) -> float:
    """Taxa de variação da distância oblíqua (m/s) em relação ao radar.
    Negativo = aproximando; positivo = afastando."""
    d0 = geodetic_to_polar(lat, lon, h, radar).distancia
    lat1, lon1 = prever_posicao(lat, lon, track_deg, gspeed_kt, 1.0)
    d1 = geodetic_to_polar(lat1, lon1, h, radar).distancia
    return d1 - d0


def polar_prevista(lat, lon, h, track_deg, gspeed_kt, radar: RadarSite,
                   dt_s: float) -> Polar:
    """Coordenadas polares previstas `dt_s` segundos à frente."""
    lat2, lon2 = prever_posicao(lat, lon, track_deg, gspeed_kt, dt_s)
    return geodetic_to_polar(lat2, lon2, h, radar)


# ---------------------------------------------------------------------------
# Radares pré-configurados (valores informados pelo usuário)
# ---------------------------------------------------------------------------
RADAR_ATLAS = RadarSite.criar(
    "Radar Atlas",
    dms_to_deg(-2, 26, 36.7250),
    dms_to_deg(-44, 7, 45.3046),
    45.150,
)
RADAR_ADOUR = RadarSite.criar(
    "Radar Adour",
    dms_to_deg(-2, 19, 51.9176),
    dms_to_deg(-44, 25, 14.4805),
    58.826,
)
RADARES = {RADAR_ATLAS.nome: RADAR_ATLAS, RADAR_ADOUR.nome: RADAR_ADOUR}
