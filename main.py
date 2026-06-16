# -*- coding: utf-8 -*-
"""
main.py — Rastreador de Aeronaves (CLA) — versão Android (Kivy)
Centro de Lançamento de Alcântara

Reaproveita radar_core.py e fr24_client.py (mesmo núcleo do app de mesa).
Recursos: seleção de radar, Atualizar/Automático, lista de aeronaves,
tela de RADAR (PPI) com radar vizinho e toque para selecionar, seguir a
aeronave selecionada (atualiza sozinha), predição e alvo travado.
"""

import math
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.graphics import Color, Line, Ellipse
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.spinner import Spinner
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

import radar_core as rc
import fr24_client as fc

REFRESH_S = 20
LEADS = ["5", "10", "15", "30", "60"]
RANGES = [25, 50, 100, 150, 200, 300, 400, 600, 800, 1000, 1200, 1500]

NAVY = (0.086, 0.208, 0.494, 1)
GOLD = (0.914, 0.706, 0.0, 1)
GREEN = (0.039, 0.49, 0.294, 1)
RED = (0.78, 0.12, 0.12, 1)
GRID = (0.76, 0.80, 0.88, 1)
WHITE = (1, 1, 1, 1)
DIMC = (0.35, 0.40, 0.46, 1)


class PPI(Widget):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        self.app.click_ppi(touch.pos)
        return True

    def redraw(self):
        self.canvas.clear()
        app = self.app
        cx = self.center_x
        cy = self.center_y
        R = min(self.width, self.height) / 2 - dp(20)
        if R <= 0:
            return
        sel_nome = app.sp_radar.text
        radar = rc.RADARES[sel_nome]
        outro_nome = next(n for n in rc.RADARES if n != sel_nome)
        outro = rc.RADARES[outro_nome]
        po = rc.geodetic_to_polar(outro.lat, outro.lon, outro.h, radar)
        dmax = max([p.distancia / 1000 for p in app.polares] + [po.distancia / 1000], default=0)
        maxr = next((x for x in RANGES if x >= dmax), RANGES[-1])
        ppk = R / maxr
        app._ppi_pts = []

        with self.canvas:
            Color(*GRID)
            for k in range(1, 5):
                Line(circle=(cx, cy, R * k / 4), width=1)
            for ang in range(0, 360, 30):
                a = math.radians(ang)
                Line(points=[cx, cy, cx + R * math.sin(a), cy + R * math.cos(a)], width=1)
            # cardeais
            self._txt("N", cx, cy + R + dp(10))
            self._txt("S", cx, cy - R - dp(10))
            self._txt("L", cx + R + dp(10), cy)
            self._txt("O", cx - R - dp(10), cy)
            # radar central
            Color(*GOLD)
            Ellipse(pos=(cx - dp(5), cy - dp(5)), size=(dp(10), dp(10)))
            self._txt(sel_nome.replace("Radar ", ""), cx, cy - dp(15), GOLD)
            # radar vizinho
            rro = min(po.distancia / 1000 * ppk, R)
            aro = math.radians(po.azimute)
            ox, oy = cx + rro * math.sin(aro), cy + rro * math.cos(aro)
            Color(*GREEN)
            Ellipse(pos=(ox - dp(5), oy - dp(5)), size=(dp(10), dp(10)))
            self._txt(outro_nome.replace("Radar ", ""), ox + dp(16), oy, GREEN)
            # aeronaves
            sel = app.sel_idx
            alvo_idx = app.achar(app.alvo)
            for i, (ac, p) in enumerate(zip(app.aeronaves, app.polares)):
                rr = min(p.distancia / 1000 * ppk, R)
                a = math.radians(p.azimute)
                bx, by = cx + rr * math.sin(a), cy + rr * math.cos(a)
                app._ppi_pts.append((bx, by, i))
                destaque = (i == sel) or (i == alvo_idx)
                Color(*(GOLD if i == alvo_idx else (NAVY)))
                s = dp(7) if destaque else dp(5)
                Ellipse(pos=(bx - s / 2, by - s / 2), size=(s, s))
                if destaque:
                    self._txt(ac.rotulo[:8], bx, by + dp(12), NAVY)
                    pf = rc.polar_prevista(ac.lat, ac.lon, ac.alt_m, ac.track,
                                           ac.speed_kt, radar, app.lead_s())
                    rr2 = min(pf.distancia / 1000 * ppk, R)
                    a2 = math.radians(pf.azimute)
                    fx, fy = cx + rr2 * math.sin(a2), cy + rr2 * math.cos(a2)
                    Color(*RED)
                    Line(points=[bx, by, fx, fy], width=1.5)
                    Line(circle=(fx, fy, dp(4)), width=1.5)

    def _txt(self, txt, x, y, cor=NAVY):
        from kivy.core.text import Label as CoreLabel
        lbl = CoreLabel(text=txt, font_size=dp(11), bold=True)
        lbl.refresh()
        t = lbl.texture
        Color(*cor)
        from kivy.graphics import Rectangle
        Rectangle(texture=t, pos=(x - t.width / 2, y - t.height / 2), size=t.size)


class Root(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=dp(8), spacing=dp(6), **kw)
        self.aeronaves = []
        self.polares = []
        self.taxas = []
        self.alvo = None
        self.seguindo = None
        self.sel_idx = -1
        self._ppi_pts = []
        self._auto_ev = None
        self._buscando = False
        self._botoes = []
        self._modo = "lista"
        self._montar()

    # ---------------- layout ----------------
    def _montar(self):
        cab = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(8))
        try:
            cab.add_widget(Image(source="cla_logo.png", size_hint_x=None, width=dp(50)))
        except Exception:
            pass
        tit = BoxLayout(orientation="vertical")
        tit.add_widget(Label(text="[b]CENTRO DE LANÇAMENTO DE ALCÂNTARA — CLA[/b]",
                             markup=True, color=NAVY, font_size="13sp", halign="left",
                             valign="middle", text_size=(dp(280), None)))
        tit.add_widget(Label(text="Rastreador de Aeronaves", color=DIMC,
                             font_size="11sp", halign="left", valign="middle",
                             text_size=(dp(280), None)))
        cab.add_widget(tit)
        self.add_widget(cab)

        c1 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.sp_radar = Spinner(text="Radar Atlas", values=list(rc.RADARES.keys()))
        self.sp_radar.bind(text=lambda *_: self._recalcular())
        self.btn = Button(text="Atualizar", background_color=NAVY)
        self.btn.bind(on_release=lambda *_: self.pesquisar())
        self.tg_auto = ToggleButton(text="Auto", size_hint_x=None, width=dp(64))
        self.tg_auto.bind(state=self._toggle_auto)
        c1.add_widget(self.sp_radar)
        c1.add_widget(self.btn)
        c1.add_widget(self.tg_auto)
        self.add_widget(c1)

        c2 = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        self.tg_lock = ToggleButton(text="Travar", size_hint_x=None, width=dp(80))
        self.tg_lock.bind(on_release=self._toggle_lock)
        self.sp_lead = Spinner(text="15", values=LEADS, size_hint_x=None, width=dp(64))
        self.sp_lead.bind(text=lambda *_: self._mostrar())
        self.tg_view = ToggleButton(text="Radar", size_hint_x=None, width=dp(80))
        self.tg_view.bind(on_release=self._troca_view)
        self.lbl_status = Label(text="Pronto", color=DIMC, font_size="11sp")
        c2.add_widget(self.tg_lock)
        c2.add_widget(Label(text="Pred(s):", color=DIMC, size_hint_x=None, width=dp(58)))
        c2.add_widget(self.sp_lead)
        c2.add_widget(self.tg_view)
        c2.add_widget(self.lbl_status)
        self.add_widget(c2)

        # área de conteúdo (lista ou PPI)
        self.conteudo = BoxLayout()
        self.lista_sv = ScrollView()
        self.lista = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self.lista.bind(minimum_height=self.lista.setter("height"))
        self.lista_sv.add_widget(self.lista)
        self.ppi = PPI(self)
        self.conteudo.add_widget(self.lista_sv)
        self.add_widget(self.conteudo)

        # cartão
        card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(150),
                         padding=dp(6))
        self.lbl_alvo = Label(text="Nenhuma aeronave selecionada", color=NAVY,
                              font_size="13sp", size_hint_y=None, height=dp(22),
                              halign="left", valign="middle")
        self.lbl_alvo.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        card.add_widget(self.lbl_alvo)
        linha = BoxLayout(size_hint_y=None, height=dp(56))
        self.v_az = self._campo(linha, "AZIMUTE")
        self.v_el = self._campo(linha, "ELEVAÇÃO")
        self.v_dist = self._campo(linha, "DIST (km)")
        card.add_widget(linha)
        self.lbl_pred = Label(text="", color=RED, font_size="12sp",
                              size_hint_y=None, height=dp(20), halign="left", valign="middle")
        self.lbl_pred.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        card.add_widget(self.lbl_pred)
        self.lbl_outro = Label(text="", color=DIMC, font_size="11sp",
                               size_hint_y=None, height=dp(18), halign="left", valign="middle")
        self.lbl_outro.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        card.add_widget(self.lbl_outro)
        self.add_widget(card)

    def _campo(self, parent, titulo):
        b = BoxLayout(orientation="vertical")
        b.add_widget(Label(text=titulo, color=DIMC, font_size="9sp",
                           size_hint_y=None, height=dp(14)))
        var = Label(text="—", color=NAVY, font_size="22sp", bold=True)
        b.add_widget(var)
        parent.add_widget(b)
        return var

    # ---------------- troca de visão ----------------
    def _troca_view(self, *_):
        self.conteudo.clear_widgets()
        if self._modo == "lista":
            self._modo = "radar"
            self.tg_view.text = "Lista"
            self.conteudo.add_widget(self.ppi)
            self.ppi.redraw()
        else:
            self._modo = "lista"
            self.tg_view.text = "Radar"
            self.conteudo.add_widget(self.lista_sv)

    # ---------------- busca ----------------
    def pesquisar(self):
        if self._buscando:
            return
        self._buscando = True
        self.btn.disabled = True
        self.lbl_status.text = "Buscando…"
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            acs = fc.buscar_aeronaves(timeout=6.0, progresso=self._prog)
            Clock.schedule_once(lambda dt: self._ok(acs), 0)
        except Exception as e:
            msg = str(e)
            Clock.schedule_once(lambda dt: self._erro(msg), 0)

    def _prog(self, i, n):
        Clock.schedule_once(lambda dt: setattr(self.lbl_status, "text", f"Setor {i}/{n}…"), 0)

    def _ok(self, acs):
        self.btn.disabled = False
        self._buscando = False
        self.aeronaves = acs
        diag = getattr(fc, "ULTIMO_DIAGNOSTICO", "")
        self.lbl_status.text = f"{len(acs)} aeronave(s)"
        self._recalcular()

    def _erro(self, msg):
        self.btn.disabled = False
        self._buscando = False
        self.lbl_status.text = "Erro: " + msg.splitlines()[0][:40]

    # ---------------- cálculo / lista ----------------
    def _recalcular(self):
        radar = rc.RADARES[self.sp_radar.text]
        dados = []
        for a in self.aeronaves:
            p = rc.geodetic_to_polar(a.lat, a.lon, a.alt_m, radar)
            r = rc.taxa_aproximacao(a.lat, a.lon, a.alt_m, a.track, a.speed_kt, radar)
            dados.append((a, p, r))
        dados.sort(key=lambda t: t[1].distancia)
        self.aeronaves = [a for a, _, _ in dados]
        self.polares = [p for _, p, _ in dados]
        self.taxas = [r for _, _, r in dados]

        ident = self.alvo or self.seguindo
        self.sel_idx = self.achar(ident) if ident else -1

        self.lista.clear_widgets()
        self._botoes = []
        for i, (a, p, r) in enumerate(dados):
            txt = (f"{a.rotulo:<9} {a.tipo or '?':<5} AZ {p.azimute:6.1f}  "
                   f"EL {p.elevacao:5.1f}  D {p.distancia/1000:6.1f}  {r:+.0f}")
            b = Button(text=txt, font_name="RobotoMono-Regular", font_size="12sp",
                       size_hint_y=None, height=dp(34), halign="left",
                       background_color=(NAVY if i == self.sel_idx else (0.9, 0.93, 0.98, 1)),
                       color=(WHITE if i == self.sel_idx else (0.1, 0.13, 0.18, 1)))
            b.bind(on_release=lambda inst, idx=i: self._clicou_lista(idx))
            self.lista.add_widget(b)
            self._botoes.append(b)

        if ident and self.sel_idx >= 0:
            self._mostrar()
        elif ident and self.sel_idx < 0:
            base = self.lbl_alvo.text.split("  ⏳")[0]
            if self.v_az.text != "—":
                self.lbl_alvo.text = base + "  ⏳ aguardando sinal"
        else:
            self._limpar()
        if self._modo == "radar":
            self.ppi.redraw()

    def achar(self, ident):
        if not ident:
            return -1
        for i, a in enumerate(self.aeronaves):
            if ident.get("hex") and a.fr24_id == ident["hex"]:
                return i
        for i, a in enumerate(self.aeronaves):
            if ident.get("callsign") and a.rotulo == ident["callsign"]:
                return i
        return -1

    def _clicou_lista(self, idx):
        self.sel_idx = idx
        a = self.aeronaves[idx]
        if not self.alvo:
            self.seguindo = {"hex": a.fr24_id, "callsign": a.rotulo}
        self._realcar_lista()
        self._mostrar()
        if self._modo == "radar":
            self.ppi.redraw()

    def click_ppi(self, pos):
        if not self._ppi_pts:
            return
        melhor, dmin = -1, dp(18)
        for (x, y, idx) in self._ppi_pts:
            d = math.hypot(pos[0] - x, pos[1] - y)
            if d < dmin:
                dmin, melhor = d, idx
        if melhor >= 0:
            self._clicou_lista(melhor)

    def _realcar_lista(self):
        for i, b in enumerate(self._botoes):
            if i == self.sel_idx:
                b.background_color = NAVY
                b.color = WHITE
            else:
                b.background_color = (0.9, 0.93, 0.98, 1)
                b.color = (0.1, 0.13, 0.18, 1)

    def lead_s(self):
        try:
            return float(self.sp_lead.text)
        except ValueError:
            return 15.0

    def _mostrar(self):
        i = self.sel_idx
        if not (0 <= i < len(self.aeronaves)):
            return
        a, p = self.aeronaves[i], self.polares[i]
        radar = rc.RADARES[self.sp_radar.text]
        rota = f"{a.origem or '?'}→{a.destino or '?'}" if (a.origem or a.destino) else ""
        trava = "  🔒" if (self.alvo and self.achar(self.alvo) == i) else ""
        self.lbl_alvo.text = (f"{a.rotulo}  •  {a.tipo or '?'}  "
                              f"{('• ' + rota + '  ') if rota else ''}•  {self.sp_radar.text}{trava}")
        self.v_az.text = f"{p.azimute:.2f}"
        self.v_el.text = f"{p.elevacao:.2f}"
        self.v_dist.text = f"{p.distancia/1000:.2f}"
        lead = self.lead_s()
        pf = rc.polar_prevista(a.lat, a.lon, a.alt_m, a.track, a.speed_kt, radar, lead)
        r = rc.taxa_aproximacao(a.lat, a.lon, a.alt_m, a.track, a.speed_kt, radar)
        mov = "aprox" if r < 0 else "afast"
        self.lbl_pred.text = (f"+{lead:.0f}s → AZ {pf.azimute:.1f}  EL {pf.elevacao:.1f}  "
                              f"D {pf.distancia/1000:.1f} km  ({r:+.0f} m/s {mov})")
        outro_nome = next(n for n in rc.RADARES if n != self.sp_radar.text)
        po = rc.geodetic_to_polar(a.lat, a.lon, a.alt_m, rc.RADARES[outro_nome])
        self.lbl_outro.text = (f"{outro_nome} → AZ {po.azimute:.1f}  EL {po.elevacao:.1f}  "
                               f"D {po.distancia/1000:.1f} km")

    def _limpar(self):
        self.lbl_alvo.text = "Nenhuma aeronave selecionada"
        self.v_az.text = self.v_el.text = self.v_dist.text = "—"
        self.lbl_pred.text = ""
        self.lbl_outro.text = ""

    # ---------------- alvo travado ----------------
    def _toggle_lock(self, *_):
        if self.alvo:
            self.alvo = None
            self.tg_lock.text = "Travar"
            self.tg_lock.state = "normal"
            return
        if not (0 <= self.sel_idx < len(self.aeronaves)):
            self.tg_lock.state = "normal"
            self.lbl_status.text = "Selecione uma aeronave"
            return
        a = self.aeronaves[self.sel_idx]
        self.alvo = {"hex": a.fr24_id, "callsign": a.rotulo}
        self.seguindo = dict(self.alvo)
        self.tg_lock.text = "Destravar"
        self._mostrar()

    # ---------------- automático ----------------
    def _toggle_auto(self, _w, state):
        if self._auto_ev:
            self._auto_ev.cancel()
            self._auto_ev = None
        if state == "down":
            self.pesquisar()
            self._auto_ev = Clock.schedule_interval(lambda dt: self.pesquisar(), REFRESH_S)


class RastreadorApp(App):
    def build(self):
        self.title = "Rastreador de Aeronaves — CLA"
        return Root()


if __name__ == "__main__":
    RastreadorApp().run()
