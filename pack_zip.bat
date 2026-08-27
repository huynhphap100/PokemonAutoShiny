@echo off
cd /d "%~dp0"
title Pokemon Auto Shiny — Pack Zip
echo Đang nén thư mục dist\PokemonAutoShiny thành file ZIP...
powershell -Command "Compress-Archive -Path 'dist\PokemonAutoShiny\*' -DestinationPath 'PokemonAutoShiny_Portable.zip' -Force"
echo [OK] Đã tạo file PokemonAutoShiny_Portable.zip
explorer /select,PokemonAutoShiny_Portable.zip
pause
