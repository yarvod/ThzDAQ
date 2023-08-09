pyInstaller main.py -n SIS_manager --onedir --icon=".\assets\logo.ico" --noconsole --windowed -y
mkdir .\dist\SIS_manager\assets
copy .\assets\* .\dist\SIS_manager\assets\
