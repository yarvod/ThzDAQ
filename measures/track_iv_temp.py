import json
import logging
import os
import time
from datetime import datetime

import numpy as np

from api import SisBlock

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

# Параметры измерения
VOLTAGE_FROM = 0  # V
VOLTAGE_TO = 0.5e-3  # 0.5 mV
NUM_POINTS = 100
MEASUREMENT_INTERVAL = 30  # секунд (1 минута)

# Инициализация SIS блока
sis2 = SisBlock(
    host="169.254.190.83",
    port=9876,
    bias_dev="DEV2",
    ctrl_dev="DEV1",
    offset_voltage=-0.187e-3,
    offset_current=-1.3e-6,
)


def measure_iv_curve():
    """
    Измеряет вольт-амперную характеристику.

    Returns:
        dict: Словарь с данными измерения
    """
    voltages_set = np.linspace(VOLTAGE_FROM, VOLTAGE_TO, NUM_POINTS)
    voltages_get = []
    currents_get = []
    timer = []
    sis2.set_bias_short_status("0")

    logger.info(
        f"Начало измерения I-V кривой: {NUM_POINTS} точек от {VOLTAGE_FROM*1e3:.3f} до {VOLTAGE_TO*1e3:.3f} mV"
    )
    start_time = time.time()
    for i, voltage in enumerate(voltages_set):
        try:
            # Устанавливаем напряжение
            sis2.set_bias_voltage(voltage)
            time.sleep(0.1)  # Небольшая задержка для стабилизации

            # Считываем реальное напряжение и ток
            voltage_measured = sis2.get_bias_voltage()
            current_measured = sis2.get_bias_current()

            if voltage_measured is not None and current_measured is not None:
                voltages_get.append(voltage_measured)
                currents_get.append(current_measured)
                timer.append(time.time() - start_time)
                logger.debug(
                    f"Точка {i+1}/{NUM_POINTS}: V={voltage_measured*1e3:.4f} mV, I={current_measured*1e6:.4f} µA"
                )
            else:
                logger.warning(
                    f"Не удалось получить данные для точки {i+1}/{NUM_POINTS}"
                )
                voltages_get.append(None)
                currents_get.append(None)

        except Exception as e:
            logger.error(f"Ошибка при измерении точки {i+1}/{NUM_POINTS}: {e}")
            voltages_get.append(None)
            currents_get.append(None)

    # Возвращаем напряжение в 0
    try:
        sis2.set_bias_voltage(0)
    except Exception as e:
        logger.error(f"Ошибка при возврате напряжения в 0: {e}")

    return {
        "voltages_get": voltages_get,
        "currents_get": currents_get,
        "timer": timer,
    }


def save_data(data, filepath):
    """
    Сохраняет данные в JSON файл.

    Args:
        data: Список словарей с данными измерений
        filepath: Путь к файлу для сохранения
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Данные сохранены в {filepath}")


def main():
    """
    Основная функция для непрерывного измерения I-V характеристик.
    """
    logger.info("Запуск программы трекинга I-V характеристик")

    # Подключаемся к прибору
    try:
        sis2.connect()
        if not sis2.test():
            logger.error("Ошибка при тестировании SIS блока")
            return
        logger.info("SIS блок успешно подключен и протестирован")
    except Exception as e:
        logger.error(f"Ошибка при подключении к SIS блоку: {e}")
        return

    # Открываем short для измерений
    try:
        sis2.set_bias_short_status("0")
        logger.info("Bias short status установлен в 0 (открыт)")
    except Exception as e:
        logger.error(f"Ошибка при установке bias short status: {e}")
        return

    # Список для хранения всех измерений
    all_measurements = []

    # Время начала измерений

    measurement_count = 0

    try:
        while True:
            start_time = time.time()
            measurement_count += 1
            current_time = time.time()

            logger.info(f"\n{'='*60}")
            logger.info(f"Измерение #{measurement_count}")
            logger.info(f"{'='*60}\n")
            start_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Выполняем измерение
            measurement_data = measure_iv_curve()

            # Добавляем метаданные
            measurement_record = {
                "datetime": start_datetime,
                "timer": measurement_data["timer"],
                "voltages_get": measurement_data["voltages_get"],
                "currents_get": measurement_data["currents_get"],
            }

            all_measurements.append(measurement_record)

            # Сохраняем данные после каждого измерения
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"measures/data/meas_iv_temp_{timestamp}.json"
            save_data(all_measurements, filepath)

            logger.info(f"Измерение #{measurement_count} завершено")
            logger.info(f"Следующее измерение через {MEASUREMENT_INTERVAL} секунд\n")

            # Ждем до следующего измерения
            time.sleep(MEASUREMENT_INTERVAL)

    except KeyboardInterrupt:
        logger.info("\nПрограмма остановлена пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        # Закрываем short и отключаемся
        try:
            sis2.set_bias_voltage(0)
            sis2.set_bias_short_status("1")
            logger.info("Bias short status установлен в 1 (закрыт)")
        except Exception as e:
            logger.error(f"Ошибка при закрытии: {e}")

        # Финальное сохранение
        if all_measurements:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"measures/data/meas_iv_temp_final_{timestamp}.json"
            save_data(all_measurements, filepath)

        logger.info("Программа завершена")


if __name__ == "__main__":
    main()
