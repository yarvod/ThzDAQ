class Config:
    # Block variables
    BLOCK_ADDRESS = "169.254.190.83"
    BLOCK_PORT = 9876
    BLOCK_BIAS_DEV = "DEV4"
    BLOCK_CTRL_DEV = "DEV3"
    BLOCK_BIAS_VOLT = 0
    BLOCK_BIAS_VOLT_FROM = 0
    BLOCK_BIAS_VOLT_TO = 7
    BLOCK_BIAS_VOLT_POINTS = 300
    BLOCK_CTRL_CURR = 0
    BLOCK_CTRL_CURR_FROM = 0
    BLOCK_CTRL_CURR_TO = 30
    BLOCK_CTRL_POINTS = 300
    BLOCK_BIAS_SCAN_THREAD = False
    BLOCK_CTRL_SCAN_THREAD = False
    BLOCK_STREAM_THREAD = False

    # Block constants
    BLOCK_BIAS_VOLT_MIN_VALUE = -30
    BLOCK_BIAS_VOLT_MAX_VALUE = 30
    BLOCK_BIAS_VOLT_POINTS_MAX = 10001
    BLOCK_CTRL_POINTS_MAX = 10001
    BLOCK_CTRL_CURR_MIN_VALUE = -100
    BLOCK_CTRL_CURR_MAX_VALUE = 100

    # VNA variables
    VNA_ADDRESS = "169.254.106.189"
    VNA_SPARAM = "S21"
    VNA_CHANNEL_FORMAT = "COMP"
    VNA_POWER = -30
    VNA_POINTS = 300
    VNA_FREQ_FROM = 2
    VNA_FREQ_TO = 12

    # VNA constants
    VNA_POWER_MIN = -60
    VNA_POWER_MAX = 0
    VNA_POINTS_MAX = 2000
    VNA_TEST_MAP = dict(
        (
            (None, "Ok"),
            ("0", "Ok"),
            ("1", "Error"),
        )
    )


config = Config()
