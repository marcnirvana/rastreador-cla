# -*- coding: utf-8 -*-
"""
fr24_client.py
==============
Cliente de dados de aeronaves com DUAS fontes selecionáveis:

  (A) API OFICIAL do Flightradar24  (USAR_FR24_OFICIAL = True)  [padrão]
      - Cobertura completa (rede terrestre + satélite).
      - UMA requisição com `bounds` cobre os 1000 km inteiros.
      - Exige um TOKEN (cole em FR24_TOKEN abaixo).
      - Base: https://fr24api.flightradar24.com/api
        Endpoint: live/flight-positions/full   (bounds = N,S,O,L)
        Cabeçalhos: Authorization: Bearer <token> e Accept-Version: v1

  (B) Redes ADS-B abertas (adsb.lol etc.) (USAR_FR24_OFICIAL = False) [fallback]
      - Gratuitas, sem token, mas cobertura esparsa no Norte do Brasil.
      - Cobrem 1000 km por um MOSAICO de consultas de 250 NM.

A interface (`Aircraft`, `buscar_aeronaves`) é a mesma — o app não muda.
"""

from __future__ import annotations
import json
import math
import ssl
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass

# ===========================================================================
#  CONFIGURAÇÃO PRINCIPAL
# ===========================================================================
# Cole aqui o seu token da API oficial do FR24 (Key management no portal):
FR24_TOKEN = ""           # <<< COLE O TOKEN ENTRE AS ASPAS

USAR_FR24_OFICIAL = False  # True = API oficial (paga); False = redes abertas gratuitas

# Raio alvo de cobertura (km) ao redor dos radares.
ALVO_KM = 1000.0

# Endpoint oficial: "full" (traz tipo/registro/origem/destino) ou "light".
FR24_BASE = "https://fr24api.flightradar24.com/api"
FR24_ENDPOINT = "live/flight-positions/full"
# Sandbox (dados estáticos, sem gastar créditos): use o token de sandbox e
# troque a base por: https://fr24api.flightradar24.com/api/sandbox

# Diagnóstico da última busca (a interface mostra isto).
ULTIMO_DIAGNOSTICO = ""

# Contextos SSL (o de fallback cobre o caso do .exe sem certificados).
_CTX = ssl.create_default_context()
_CTX_FALLBACK = ssl._create_unverified_context()

# Posição dos radares e centro (ponto médio).
_RADARES_LATLON = [(-2.443535, -44.129251), (-2.331088, -44.420689)]
_CENTRO_LAT = sum(p[0] for p in _RADARES_LATLON) / len(_RADARES_LATLON)
_CENTRO_LON = sum(p[1] for p in _RADARES_LATLON) / len(_RADARES_LATLON)

HEADERS_BASE = {
    "User-Agent": "RastreadorAeronaves/3.0 (uso local)",
    "Accept": "application/json",
}


# ===========================================================================
#  Modelo de aeronave (mesma interface usada pela interface gráfica)
# ===========================================================================
@dataclass
class Aircraft:
    fr24_id: str
    callsign: str
    registration: str
    tipo: str
    lat: float
    lon: float
    alt_ft: float
    alt_m: float
    track: float
    speed_kt: float
    origem: str
    destino: str
    voo: str

    @property
    def rotulo(self) -> str:
        cs = self.callsign or self.voo or self.registration or "Não identificado"
        return cs.strip()


def _to_float(v, default=0.0) -> float:
    try:
        if isinstance(v, str) and v.lower() in ("ground", "", "none"):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return default


def _get_json(url: str, timeout: float, headers: dict | None = None):
    h = dict(HEADERS_BASE)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.URLError as exc:
        motivo = str(getattr(exc, "reason", exc)).upper()
        if "CERTIFICATE" in motivo or "SSL" in motivo:
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX_FALLBACK) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        raise


# ===========================================================================
#  (A) API OFICIAL DO FR24
# ===========================================================================
def _bounds_alvo() -> str:
    dlat = ALVO_KM / 111.0
    dlon = ALVO_KM / (111.0 * math.cos(math.radians(_CENTRO_LAT)))
    norte = _CENTRO_LAT + dlat
    sul = _CENTRO_LAT - dlat
    oeste = _CENTRO_LON - dlon
    leste = _CENTRO_LON + dlon
    return f"{norte:.4f},{sul:.4f},{oeste:.4f},{leste:.4f}"   # N,S,O,L


def _parse_fr24(it: dict) -> Aircraft | None:
    lat, lon = _to_float(it.get("lat")), _to_float(it.get("lon"))
    if lat == 0.0 and lon == 0.0:
        return None
    alt_ft = _to_float(it.get("alt"))
    return Aircraft(
        fr24_id=str(it.get("fr24_id", "") or ""),
        callsign=str(it.get("callsign", "") or "").strip(),
        registration=str(it.get("reg", "") or ""),
        tipo=str(it.get("type", "") or ""),
        lat=lat, lon=lon,
        alt_ft=alt_ft, alt_m=alt_ft * 0.3048,
        track=_to_float(it.get("track")),
        speed_kt=_to_float(it.get("gspeed")),
        origem=str(it.get("orig_icao") or it.get("orig_iata") or ""),
        destino=str(it.get("dest_icao") or it.get("dest_iata") or ""),
        voo=str(it.get("flight", "") or ""),
    )


def _buscar_fr24(timeout: float):
    global ULTIMO_DIAGNOSTICO
    if not FR24_TOKEN.strip():
        raise RuntimeError(
            "Token da API oficial do FR24 não configurado.\n"
            "Abra fr24_client.py, cole seu token em FR24_TOKEN = \"...\" e "
            "recompile.\n(O token vem do portal fr24api.flightradar24.com, "
            "em Key management.)")

    url = f"{FR24_BASE}/{FR24_ENDPOINT}?bounds={_bounds_alvo()}"
    headers = {
        "Authorization": f"Bearer {FR24_TOKEN.strip()}",
        "Accept-Version": "v1",
    }
    try:
        data = _get_json(url, timeout, headers=headers)
    except urllib.error.HTTPError as exc:
        corpo = ""
        try:
            corpo = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        dica = {
            401: "token inválido ou ausente",
            403: "token sem permissão para este endpoint/plano",
            402: "sem créditos no plano da API",
            429: "limite de requisições atingido (aguarde alguns segundos)",
        }.get(exc.code, "")
        raise RuntimeError(
            f"FR24 API recusou (HTTP {exc.code}{': ' + dica if dica else ''}).\n{corpo}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Sem acesso à API do FR24: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Resposta da API do FR24 não veio em JSON.") from exc

    itens = data.get("data") or []
    aeronaves = []
    for it in itens:
        obj = _parse_fr24(it)
        if obj:
            aeronaves.append(obj)
    aeronaves.sort(key=lambda a: a.rotulo)
    ULTIMO_DIAGNOSTICO = f"{len(aeronaves)} aeronaves | FR24 API oficial ({_bounds_alvo()})"
    return aeronaves


# ===========================================================================
#  (B) REDES ADS-B ABERTAS (fallback, por mosaico de 250 NM)
# ===========================================================================
FONTES = [
    "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}",
    "https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}",
    "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{nm}",
]
TILE_NM = 250
TILE_KM = TILE_NM * 1.852


def _gerar_tiles(lat_c, lon_c, alvo_km):
    pts = [(lat_c, lon_c)]
    passo = TILE_KM * 1.3
    cobertura = TILE_KM
    r = passo
    while cobertura < alvo_km:
        n = max(6, int(round(2 * math.pi * r / passo)))
        for k in range(n):
            ang = 2 * math.pi * k / n
            dlat = (r * math.cos(ang)) / 111.0
            dlon = (r * math.sin(ang)) / (111.0 * math.cos(math.radians(lat_c)))
            pts.append((lat_c + dlat, lon_c + dlon))
        cobertura = r + TILE_KM
        r += passo
    return pts


def _parse_ac(ac: dict) -> Aircraft | None:
    lat, lon = _to_float(ac.get("lat")), _to_float(ac.get("lon"))
    if lat == 0.0 and lon == 0.0:
        return None
    alt_ft = _to_float(ac.get("alt_baro", ac.get("alt_geom", 0)))
    return Aircraft(
        fr24_id=str(ac.get("hex", "")),
        callsign=str(ac.get("flight", "") or "").strip(),
        registration=str(ac.get("r", "") or ""),
        tipo=str(ac.get("t", "") or ""),
        lat=lat, lon=lon,
        alt_ft=alt_ft, alt_m=alt_ft * 0.3048,
        track=_to_float(ac.get("track")),
        speed_kt=_to_float(ac.get("gs")),
        origem="", destino="",
        voo=str(ac.get("flight", "") or "").strip(),
    )


def _buscar_aberto(timeout: float, progresso=None):
    global ULTIMO_DIAGNOSTICO
    tiles = _gerar_tiles(_CENTRO_LAT, _CENTRO_LON, ALVO_KM)
    encontrados: dict[str, Aircraft] = {}
    erros, tiles_ok = [], 0
    uso = {}
    fonte_ativa = None   # ao achar uma rede que responde, reutiliza nos demais setores
    for idx, (lat, lon) in enumerate(tiles):
        if progresso:
            progresso(idx + 1, len(tiles))
        ordem = ([fonte_ativa] + [f for f in FONTES if f != fonte_ativa]
                 if fonte_ativa else list(FONTES))
        for fonte in ordem:
            url = fonte.format(lat=f"{lat:.6f}", lon=f"{lon:.6f}", nm=TILE_NM)
            host = (urllib.parse.urlparse(fonte).hostname or fonte
                    ).replace("api.", "").replace("opendata.", "")
            try:
                data = _get_json(url, timeout)
            except urllib.error.HTTPError as exc:
                erros.append(f"{host}:HTTP {exc.code}"); continue
            except urllib.error.URLError as exc:
                erros.append(f"{host}:{exc.reason}"); continue
            except Exception as exc:
                erros.append(f"{host}:{exc}"); continue
            for ac in (data.get("ac") or []):
                obj = _parse_ac(ac)
                if obj is None:
                    continue
                encontrados[obj.fr24_id or f"{obj.lat:.4f},{obj.lon:.4f}"] = obj
            fonte_ativa = fonte
            uso[host] = uso.get(host, 0) + 1
            tiles_ok += 1
            break
        time.sleep(0.2)
    fontes_txt = ", ".join(f"{h}×{n}" for h, n in uso.items()) or "nenhuma"
    ULTIMO_DIAGNOSTICO = (f"{len(encontrados)} aeronaves | {tiles_ok}/{len(tiles)} "
                          f"setores | redes abertas: {fontes_txt}")
    if not encontrados and tiles_ok == 0:
        raise RuntimeError("Não foi possível acessar nenhuma rede ADS-B aberta.\n"
                           + " | ".join(list(dict.fromkeys(erros))[:6]))
    aeronaves = list(encontrados.values())
    aeronaves.sort(key=lambda a: a.rotulo)
    return aeronaves


# ===========================================================================
#  Função pública (escolhe a fonte)
# ===========================================================================
def buscar_aeronaves(timeout: float = 8.0, progresso=None):
    if USAR_FR24_OFICIAL:
        return _buscar_fr24(timeout)
    return _buscar_aberto(timeout, progresso)
