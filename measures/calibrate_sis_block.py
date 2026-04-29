from api import SocketAdapter
import json


def cal_sis1():
    s1 = SocketAdapter(host="169.254.190.83", port=9876)
    # sis1 b2
    value = {
        "CurrentADC": [2.7199096308549997e-09, -0.02362622693181038],
        "CurrentDAC": [-1382090, 32661.900390625],
        "CurrentLimits": [-0.0020000000949949026, 0.0020000000949949026],
        "CurrentMonitorResistance": 10,
        "CurrentStep": 9.999999974752427e-07,
        "VoltageAdc": [6.597875135128106e-09, -0.057308197021484375],
        "VoltageDac": [-1177910, 32684.30078125],
        "VoltageLimits": [-0.019999999552965164, 0.019999999552965164],
        "VoltageStep": 9.999999747378752e-06,
    }
    s1.query(f"BIAS:DEV2:EEPR {json.dumps(value)}")

    value = {
        "CurrentADC": [5.4767381740816745e-09, -0.04757314547896385],
        "CurrentDAC": [-1322560, 32801.19921875],
        "CurrentLimits": [-0.0020000000949949026, 0.0020000000949949026],
        "CurrentMonitorResistance": 20,
        "CurrentStep": 9.999999974752427e-07,
        "VoltageAdc": [6.567045574001895e-09, -0.05704041197896004],
        "VoltageDac": [-1322980, 32810.3984375],
        "VoltageLimits": [-0.019999999552965164, 0.019999999552965164],
        "VoltageStep": 9.999999747378752e-06,
    }
    s1.query(f"BIAS:DEV4:EEPR {json.dumps(value)}")


def cal_sis2():
    s2 = SocketAdapter(host="169.254.71.6", port=9876)

    s2.query("BIAS:DEV4:VADC [6.54495619339726e-09, -0.05711805797220779]")
    s2.query("BIAS:DEV4:CADC [3.339752801150731e-09, -0.029063230853524875]")
    s2.query("BIAS:DEV2:VADC [6.528142486063483e-09, -0.056971324169590866]")
    s2.query("BIAS:DEV2:CADC [3.2778026043888086e-09, -0.028452610355275732]")
    s2.query("GENeral:DEVice2:WriteEEProm")
    s2.query("GENeral:DEVice4:WriteEEProm")


def main():
    try:
        print("Start calibrate SIS block 1")
        cal_sis1()
        print("Finish calibrate SIS block 1")
    except:
        print("Unable calibrate SIS block 1")
    try:
        print("Start calibrate SIS block 2")
        cal_sis2()
        print("Finish calibrate SIS block 2")
    except:
        print("Unable calibrate SIS block 2")


if __name__ == "__main__":
    main()
