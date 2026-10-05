package dev.bww;
import org.junit.Test;
import static org.junit.Assert.*;
public class BluetoothServicesTest {
    @Test public void namedEsp32UsesSecureSppFirst() { assertArrayEquals(new java.util.UUID[]{BluetoothServices.SPP, BluetoothServices.BWW}, BluetoothServices.forDevice("BWW-ESP32")); }
    @Test public void computersKeepCustomBwwServiceAndHaveSppFallback() { assertArrayEquals(new java.util.UUID[]{BluetoothServices.BWW, BluetoothServices.SPP}, BluetoothServices.forDevice("My computer")); assertEquals(BluetoothServices.BWW, BluetoothServices.forDevice(null)[0]); }
    @Test public void limitsMatchBothServerTypes() { assertEquals(16384, BluetoothServices.siteLimit(16384)); assertEquals(524288, BluetoothServices.siteLimit(524288)); }
    @Test public void rejectsInvalidAdvertisedLimits() { for (int limit : new int[]{0, -1, 524289, Integer.MAX_VALUE}) { try { BluetoothServices.siteLimit(limit); fail(); } catch (IllegalArgumentException expected) {} } }
}
