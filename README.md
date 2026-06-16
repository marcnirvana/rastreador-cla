# Rastreador de Aeronaves CLA — versão Android (Kivy)

App Android do Centro de Lançamento de Alcântara. Reaproveita o **mesmo núcleo**
do app de mesa (`radar_core.py` e `fr24_client.py`): cobertura de 1000 km por
redes ADS-B abertas, conversão para coordenadas polares (AZ/EL/DIST), predição,
taxa de aproximação. A interface foi refeita em **Kivy** (que roda no Android).

Recursos: seleção de radar, Atualizar/Automático, lista de aeronaves, tela de
RADAR (PPI) com o radar vizinho e **toque para selecionar**, **seguir** a
aeronave selecionada (atualiza sozinha), **predição** e **alvo travado**.

## Por que não é o mesmo `.exe`/Tkinter?

O app de mesa usa Tkinter, que **não existe no Android**. Por isso a interface
é em Kivy. O cálculo e os dados são idênticos (mesmos arquivos).

## Conteúdo

```
main.py                          # app Kivy (interface Android)
radar_core.py                    # núcleo de cálculo (idêntico ao do desktop)
fr24_client.py                   # cliente ADS-B (idêntico ao do desktop)
cla_icon.png                     # ícone do app (brasão do CLA)
cla_logo.png                     # logo do cabeçalho
buildozer.spec                   # configuração do build Android
.github/workflows/build-apk.yml  # gera o APK na nuvem (GitHub Actions)
```

## Como gerar o APK

### Opção 1 — Na nuvem (recomendado, sem instalar nada)
1. Suba **todos** estes arquivos para um repositório no GitHub (mantenha a pasta
   `.github/workflows/`).
2. Aba **Actions** → o job **"Compilar APK (Android)"** roda sozinho.
   A 1ª vez leva ~20–35 min (baixa SDK/NDK).
3. Baixe o artefato **`rastreadorcla-apk`** → contém o `.apk`.
4. No celular/tablet: ative "instalar de fontes desconhecidas" e instale.

### Opção 2 — Local (Linux ou WSL no Windows)
```bash
sudo apt-get update
sudo apt-get install -y git zip unzip openjdk-17-jdk python3-pip \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
  libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev build-essential ccache
pip install "cython==0.29.36" buildozer
buildozer android debug      # o APK sai em bin/
```

## Uso no Android

- Toque em **Atualizar** (ou ligue **Auto**) para buscar aeronaves.
- Toque numa aeronave (na lista **ou** no PPI) para **selecionar e seguir** —
  AZ/EL/DIST passam a se atualizar sozinhos a cada ciclo.
- Botão **Radar/Lista** alterna entre a tabela e a tela PPI.
- **Travar** fixa o alvo; **Pred(s)** define o tempo da predição.

## Observações

- A cobertura depende das redes ADS-B abertas (esparsa no Norte do Brasil),
  igual ao app de mesa. Para cobertura completa, a API oficial do FR24 (paga)
  já está preparada em `fr24_client.py` (`USAR_FR24_OFICIAL = True` + token).
- O build é **debug** (instalável por sideload). Para Play Store, seria preciso
  um build `release` assinado.
