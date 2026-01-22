#pragma once

#include <Arduino.h>

template <typename T>
static auto setDhcpHostnameIfSupported(T &eth, const char *name, int)
  -> decltype(((T *)0)->setHostname((const char *)0), void()) {
  eth.setHostname(name);
  Serial.print(F("DHCP hostname: "));
  Serial.println(name);
}

template <typename T>
static void setDhcpHostnameIfSupported(T &, const char *, long) {
  Serial.println(F("DHCP hostname not supported by this Ethernet library."));
}
