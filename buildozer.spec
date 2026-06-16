[app]
title = Rastreador de Aeronaves CLA
package.name = rastreadorcla
package.domain = br.cla.alcantara

source.dir = .
source.include_exts = py,png,jpg,kv
version = 3.0

# Núcleo usa só urllib/ssl/json/math (stdlib) + Kivy para a interface
requirements = python3,kivy==2.3.0

orientation = portrait
fullscreen = 0

# Ícone do app (brasão do CLA)
icon.filename = cla_icon.png

# Permissões (iguais às do app de mesa)
android.permissions = INTERNET,ACCESS_NETWORK_STATE

android.api = 34
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
