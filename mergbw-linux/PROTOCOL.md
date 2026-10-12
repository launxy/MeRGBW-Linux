# MeRGBW 1.6.3 — análisis forense y protocolo BLE

Fuente: `/home/launxy/Downloads/MeRGBW_1.6.3_APKPure.xapk`
(29 960 099 bytes, `manifest.json` xapk_version 2, package
`com.mergbw.android`, versionCode 35, versionName 1.6.3).

Decompilado con jadx 1.5.6 a `/tmp/opencode/mergbw-decompiled`
(12 144 clases, 154 errores menores de decompilación, irrelevantes para
el núcleo BLE).

## 1. Contenedor

XAPK = ZIP. `unzip -l` muestra:

- `com.mergbw.android.apk` (base, ~28 MB, 5 dex: classes..classes5.dex)
- `config.{ar,de,en,es,fr,hi,in,it,ja,ko,my,pt,ru,th,tr,vi,zh}.apk` (idiomas)
- `config.arm64_v8a.apk` (solo `lib/arm64-v8a/libdatastore_shared_counter.so`)
- `config.xhdpi.apk`, `icon.png`, `manifest.json`

No hay cifrado ni ofuscación relevante del protocolo. El APK base es
Kotlin + AndroidX + FastBLE (`com.clj.fastble`), Room, Retrofit/OkHttp,
Gson/Fastjson, Firebase, AdMob. Sin `.so` propio: todo el BLE es Java.

Permisos (manifest): `BLUETOOTH`, `BLUETOOTH_ADMIN`, `BLUETOOTH_SCAN`,
`BLUETOOTH_CONNECT`, `ACCESS_FINE/COARSE_LOCATION`, `INTERNET`,
`ACCESS_WIFI_STATE`, `RECORD_AUDIO` (modo música con micrófono),
`FOREGROUND_SERVICE_MEDIA_PLAYBACK`, etc.

## 2. GATT (com.mergbw.core.Constants)

| Rol | UUID |
|---|---|
| Servicio primario | `0000fff0-0000-1000-8000-00805f9b34fb` |
| Write (sin respuesta) | `0000fff3-0000-1000-8000-00805f9b34fb` |
| Notify | `0000fff4-0000-1000-8000-00805f9b34fb` |

Flujo (`RGBDeviceManager`): connect → `setMtu(247)` → `setNotify(FFF4)` →
cola `SendCommandQueue` por MAC → `write(FFF3, data, response=false)`.
Las respuestas llegan por notify; `data[1]` = CMD de respuesta.
MTU por defecto 20 si falla la negociación.

> Linux: la característica anuncia `write` y `write-without-response`, pero
> el firmware Telink solo contesta al **Write With Response** (FastBLE en
> Android usa el tipo por defecto = con respuesta). En bleak hay que usar
> `response=True`. Verificado con equipo real TG201A.

## 3. Escaneo (AddDeviceViewModel.scanDevice)

Sin filtro hardware (`BleScanRuleConfig.Builder().build()`), filtra por
software parseando el scanRecord como lista AD `[len, type, datos...]`:

- Acepta si existe AD con `type == 0x02`, `len == 3`, `datos == [0x19, 0x35]`
  (UUID 16-bit `0x3519`, little-endian en el aire).
- `analyseFactoryInfo` sobre AD `type == 0xFF` (manufacturer):
  - `data[10]` = deviceType (1-8)
  - `data[11:21]` = modelo ASCII (10 bytes, ej. `TG201`, `TG609`, `TG610`)
  - `data[23:27]` = factoryID (int big-endian)
- Guarda `name + mac + deviceType + model + factoryID`.

En Linux/BlueZ el scanRecord crudo no siempre está disponible; por eso el
escáner marca candidatos por nombre/manufacturer/UUID y permite conexión
directa por MAC.

## 4. Paquete (com.mergbw.core.ble.CommandUtils — código exacto)

```java
CMD_HEAD = 0x55 (85); CMD_SEQUENCE = 0xFF (-1 como byte)
// Respuestas del firmware: misma estructura pero cabecera 0x56.
// Capturas reales TG201A: 560EFF060294 (bind), 5601FF0600A3 (ack power).
getCommand(cmd, payload):
  len = 5 + payload.length
  buf = [0x55, cmd, 0xFF, len, payload..., 0x00]
  suma = Σ(buf[i] & 0xFF); while (suma > 255) suma &= 255
  buf[len-1] = (~suma) & 0xFF
checkValid(data):
  suma = Σ(data[0..n-2] & 0xFF) plegada igual
  válido ⟺ ((~(suma + data[n-1]_con_signo)) & 0xFF) == 0
getByteArray(int): u16 big-endian (2 bytes)
int2ByteArray(int): u32 big-endian
getSeqCommand(cmd, chunk, seq): igual pero buf[2]=seq, para fragmentados
```

Es decir: `[55, CMD, SEQ, LEN, PAYLOAD..., CS]`, `CS = (~Σ) & FF`.

## 5. Comandos (com.mergbw.core.ble.CommandList)

| CMD (dec) | Nombre Java | Payload (request) | Notas |
|---|---|---|---|
| 0 | SYNC_STATUS | vacío | Respuesta = estado (ver §7). Tras conectar siempre se envía 0 + 12. |
| 1 | POWER | `[0/1]` | `BaseDeviceDetailViewModel.setPower`, `HomeViewModel` tras CMD 1 re-pide 0 |
| 2 | FIRMWARE_INFO | vacío | Respuesta `data[4..6]` = 3 chars ASCII versión |
| 3 | SET_COLOR | según tipo | Tipo 1/7: HSV `[hue_hi,hue_lo,sat_hi,sat_lo]` (`ColorUtils.getHSVColorData`: hue grados u16be, sat = s*1000 u16be). Tipos 5/6: RGB `[R,G,B]`. Audio: `[R,G,B]` por micrófono. |
| 4 | SET_PART_COLOR | 61 B fragmentado `[0x01, 20×RGB]` | `setSubColor`: 20 sub-LEDs, MTU-8 por fragmento, seq 1..n-1 y `0xFF` el último |
| 5 | SET_BRIGHTNESS | tipo 1: u16be `(p+5)*10`; resto: 1 byte `(p+5)` o `p` | `DeviceDetailViewModel1.setBrightness` vs `.../6` |
| 6 | SET_MODE | 1-2 bytes `[sceneIndex]` | Escenas clásicas/festival/otros (índices en `ViewDataUtils.getSceneData`) |
| 7 | SET_MUSIC_MODE | `[mode]` | Modelos en `getMusicModel` (1..6) |
| 8 | SET_MUSIC_SENS | `[60..100]` | Mapeo: `v = p/100*(100-60)+60` |
| 9 | SET_DIY_MODE | fragmentado `[0x01,style,time,count, n×60B]` | `sendDIYColor`: COUNT entradas × 20 RGB; orden invertido |
| 10 | SET_TIMER | 8 B `[oe,oh,om,oweek, ce,ch,cm,cweek]` | `DeviceAlarmActivity.setAlarm`; week = bitmask `"0"+Dom..Lun` |
| 11 | SET_LED_NUM | u16be | Tras OK el equipo re-pide sync (CMD 0) |
| 12 | SYNC_TIME | 8 B `[Yhi,Ylo,M,D,h,m,s,week]` | `HomeViewModel.syncInfo` con `Calendar`; week 1=Lun..7=Dom |
| 13 | CONFIG_MODE | — | Reservado/config |
| 14 | CHECK_BIND | `android_id[0:12]` como hex bytes, o vacío | Tipos 1/4: `AppUtils.getUniId()`; tipos 6/7: vacío. Respuesta `data[4]`: 1=bound, 2=unbind, 3=timeout, 0=ok(6/7) |
| 15 | SET_MODE_SPEED | `[speed]` | Junto a CMD 6 |
| 16 | SET_WHITE_LIGHT | — | Tipos bombilla |
| 17 | SET_WHITE_BRIGHTNESS | `[v]` | `setWhiteBrightness`, `setColdAndWarmBrightness` |
| 18 | SET_COLD_WARM | `[coldBri,warmBri,coldPct,warmPct]` | Tipos 7/8 ceiling; variante warm slider |
| 242-246 | CONFIG_* | — | `REMOTE/INFO/RGB_ORDER/LIMIT/COMPLETE` (área fábrica) |

## 6. Bind / init por tipo (HomeViewModel.deviceInitData)

- Tipos 1, 4 → envía CMD 14 con uniId; si respuesta `1` → bound + `syncInfo` (0 + 12).
- Tipos 2, 3, 5 → bound directo + `syncInfo`.
- Tipos 6, 7 → envía CMD 14 vacío; si respuesta `data[4]==0` → bound + `syncInfo`.

## 7. Estado CMD 0 (ViewDataUtils.analyseSyncData)

Índices sobre el paquete completo (`data[0]=0x55, data[1]=0, ...`):

- Tipos 1/2/4: `open=data[4]==1`, `bri=(u16(data[5],data[6])/10)-5`,
  openAlarm `data[7..10]`, closeAlarm `data[11..14]`,
  `ledNum=u16(data[15],data[16])`, `sens=data[17]`.
- Tipo 3 (star): `bri=data[5]-5`, alarmas `6..13`, `starBri=data[14]`, `motor=data[15]`.
- Tipo 5 (sunset): `bri=data[5]-5`, alarmas `6..13`.
- Tipo 6 (bulb): `bri=data[5]-5`, `whiteOpen=data[6]==1`, `whiteBri=data[7]-5`, alarmas `8..15`.
- Tipos 7/8 (ceiling): `bri=data[5]-5`, alarmas `6..13`, si `len>=18`:
  `cold=data[14], warm=data[15], coldPct=data[16], warmPct=data[17]`; si
  `len>=19`: `sens=data[18]`.

Alarma: `{set: b==1, h, m, week: 8 bools del byte}`.

## 8. Servidores / nube (solo referencia, no usados en Linux)

- `SERVER_ADDRESS = http://47.251.33.234:7788`, iconos `.../userIcon/`
- Fábrica: `http://brand.mergbw.com[:8080]`, test `brandtest...`
- Firebase + AdMob (`SUPPORT_AD=true`). Nada de esto es necesario para BLE local.

## 9. Firmware incluido

`assets/firmware/simpleBlePeripheral-TG201.hex16`,
`...-TG609.hex16`, `...-TG610.hex16` (~235 KB c/u). OTA vía `DeviceUpgrade*`
(no portada; requiere captura de sesión con equipo real).

## 10. Correspondencia de archivos implementados

- `mergbw/protocol.py` ← `CommandUtils.java`, `CommandList.java`,
  `Constants.java` (UUIDs), `ColorUtils.java` (`getHSVColorData`,
  `getSubColor`), `DataUtils.java`, `StringUtils.java` (week, hex),
  `ViewDataUtils.analyseSyncData`, `DeviceAlarmSyncHelper.buildAlarmCommand`,
  `HomeViewModel.syncInfo`, `AppUtils.getUniId`.
- `mergbw/device.py` ← `RGBDeviceManager.java` (cola, MTU, notify),
  `AddDeviceViewModel.scanDevice/analyseCastData/analyseFactoryInfo`.
- `mergbw/cli.py` ← `BaseDeviceDetailViewModel` + `DeviceDetailViewModel{1,3,5,6,7}`
  + `DeviceInfoViewModel.setLedNum` + `DeviceAlarmActivity.setAlarm`.
