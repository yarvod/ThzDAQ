res = b"$TEA,086,040,031,000,3798\x0D"
res = res.decode("utf-8").split(",")
print(res[1], res[2])
