# Программа для управления СИС-смесителем и измерений его характеристик
__Разработана в рамках государственного задания ФИАН № FFMR-2024-0013 "ИССЛЕДОВАНИЕ КОСМИЧЕСКИХ ОБЪЕКТОВ И ЯВЛЕНИЙ В СУБМИЛЛИМЕТРОВОМ ДИАПАЗОНЕ ДЛИН ВОЛН; АСТРОФИЗИКА И КОСМОЛОГИЯ"__


## Системные требования:
- Тип ЭВМ: Двухъядерный или более мощный процессор x64 и не менее 4 ГБ оперативной памяти.
- Для работы программы необходимо установить библиотеки Python: PySide6, pyqtgraph, numpy, Scipy, pymodbus, pyserial, requests, alvar (Подробнее в requirements/base.txt)
- Язык Python3
- ОС: Windows 10 64-bit, Mac OS Big Sur (11), Linux Ubuntu 18.04 и выше
- Объем программы 432 KB

## Установка и запуск
1. Создаем виртуальное окружение venv
```bash
python3 -m venv venv 
```
2. Активируем виртуальное окружение venv
Linux/MacOS:
```bash
source venv/bin/activate 
```
Windows:
```batch
venv/Scripts/activate.bat
```
3. Устанавливаем зависимости
```bash
pip install -r requirements/base.txt
```
4. Запускаем программу
```bash
python main.py
```

## Создание .exe или .app приложения

Linux/MacOS:
```bash
sh build.sh
```
Windows:
```batch
build.bat
```

