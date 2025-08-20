from api import SocketAdapter


def main():

    # s1 = SocketAdapter(host="169.254.190.83", port=9876)
    # s1.query("BIAS:DEV4:VADC [6.56704542211282e-09, -0.05704041196301819]")
    # s1.query("BIAS:DEV4:CADC [5.476738214604828e-09, -0.047573144569453]")
    # s1.query("BIAS:DEV2:VADC [6.597875332219662e-09, -0.0573081961277745]")
    # s1.query("BIAS:DEV2:CADC [2.7199097173824647e-09, -0.023626226620772024]")
    # s1.query("GENeral:DEVice2:WriteEEProm")
    # s1.query("GENeral:DEVice4:WriteEEProm")

    s2 = SocketAdapter(host="169.254.71.6", port=9876)
    s2.query("BIAS:DEV4:VADC [6.54495619339726e-09, -0.05711805797220779]")
    s2.query("BIAS:DEV4:CADC [3.339752801150731e-09, -0.029063230853524875]")
    s2.query("BIAS:DEV2:VADC [6.528142486063483e-09, -0.056971324169590866]")
    s2.query("BIAS:DEV2:CADC [3.2778026043888086e-09, -0.028452610355275732]")
    s2.query("GENeral:DEVice2:WriteEEProm")
    s2.query("GENeral:DEVice4:WriteEEProm")


if __name__ == "__main__":
    main()
