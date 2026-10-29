# thzdaq-analysis

Calculations on measured data of a SIS mixer bench: I-V curve analysis (Rn, Rj, Q, the
gap), noise temperature from hot/cold powers, shot noise, 2SB sideband rejection. Arrays
and numbers in, results out: no files, no instruments, no daemon; it depends only on
`numpy`. The bench daemon runs it as operations (`analyze_iv`); scripts and notebooks
may import it directly (`pip install thzdaq[analysis]`).
