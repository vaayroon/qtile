*. primero se instala

# Ejemplo para Debian/Ubuntu
sudo apt install xserver-xorg libpangocairo-1.0-0 libcairo2-dev libpango1.0-dev libxcb-render0-dev libffi-dev -y

*. Instalar

sudo apt install python3-venv -y

*. clonamos el proyecto

cd .config
git clone ...
cd qtile

*. Luego configuramos el entorno virtual.

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
# Instalar en este orden para evitar errores de compilación
pip install xcffib
pip install --no-cache-dir cairocffi
pip install dbus-fast qtile==0.35.0

*. Instalar

sudo apt install kitty qterminal -y

*. Instalar fuentes: CaskaydiaCove Nerd Font
bajar de ner fonts y mover a /usr/share/fonts
luego recargar cache

instalar gnome tweaks
cambiar la fuente de interfaz de gnome


