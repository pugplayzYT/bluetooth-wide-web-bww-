package dev.bww;
import java.util.UUID;
final class BluetoothServices {
    static final UUID BWW = UUID.fromString("731e9c72-48a1-4e6b-a842-d1ea7cc89010");
    static final UUID SPP = UUID.fromString("00001101-0000-1000-8000-00805f9b34fb");
    static UUID[] forDevice(String name) {
        return name != null && name.startsWith("BWW-ESP32") ? new UUID[]{SPP, BWW} : new UUID[]{BWW, SPP};
    }
    static int siteLimit(int advertised) {
        if (advertised < 1 || advertised > 524288) throw new IllegalArgumentException("Unsupported server site size limit");
        return advertised;
    }
}
