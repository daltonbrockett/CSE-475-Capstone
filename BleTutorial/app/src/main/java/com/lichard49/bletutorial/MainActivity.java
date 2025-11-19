package com.lichard49.bletutorial;

import android.Manifest;
import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanRecord;
import android.bluetooth.BluetoothDevice;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.util.Log;
import android.widget.Button;
import android.widget.TextView;
import android.app.NotificationChannel;
import android.app.NotificationManager;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.app.NotificationCompat;

import java.nio.charset.StandardCharsets;

// GATT
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.BluetoothGattDescriptor;

//Bluetooth Low Energy (BLE) peripheral that exposes a few custom services and characteristics
// PI bluetooth pairs with this BLE APP, just need to check how this app updates on the real phone we have
// Broadcast a BLE alert packet that nearby paired phones detect instantly.
//The  app (if running) displays a popup

public class MainActivity extends AppCompatActivity {
    private static final String TAG = "BLE_Debug";
    private static final String CHANNEL_ID = "alerts";
    private TextView status; // text
    private BluetoothLeScanner scanner;
    private BluetoothAdapter adapter;
    private Button scanButton;
    private BluetoothGatt gatt;

    // replace with actual UUID and pi name
    private static final String TARGET_NAME = "RPi";
    // UUID for the service
    private static final java.util.UUID ALERT_SERVICE_UUID =
            java.util.UUID.fromString("11111111-2222-3333-4444-56789abcdef0");
    // custom chara identifier for pi, UUID for the characteristic under the service
    private static final java.util.UUID ALERT_CHAR_UUID =
            java.util.UUID.fromString("11111111-2222-3333-4444-56789abcdef1");
    /* BluetoothGattCharacteristic alertChar = service.getCharacteristic(ALERT_CHAR_UUID);
        gatt.readCharacteristic(sosChar);
    */
    // standard bluetooth UUID for notification, subscribing to updates
    private static final java.util.UUID CCCD_UUID =
            java.util.UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private final ScanCallback scanCallback = new ScanCallback() {
        @SuppressLint({"SetTextI18n", "MissingPermission"})
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            Log.d(TAG, "-----------------------------------------------------");
            Log.d(TAG, "onScanResult called");

            BluetoothDevice device = result.getDevice();
            String name = device.getName();

            Log.d(TAG, "   Device found:");
            Log.d(TAG, "   Name: " + (name != null ? name : "NULL"));
            Log.d(TAG, "   Address: " + device.getAddress());
            Log.d(TAG, "   RSSI: " + result.getRssi());

            boolean nameMatch = (name != null && name.equals(TARGET_NAME));
            boolean serviceMatch = false;

            ScanRecord rec = result.getScanRecord();
            if (rec != null) {
                Log.d(TAG, "   ScanRecord exists");
                if (rec.getServiceUuids() != null) {
                    Log.d(TAG, "   Service UUIDs found: " + rec.getServiceUuids().size());
                    for (android.os.ParcelUuid uuid : rec.getServiceUuids()) {
                        Log.d(TAG, "   - Service: " + uuid.getUuid());
                        if (uuid.getUuid().equals(ALERT_SERVICE_UUID)) {
                            serviceMatch = true;
                            Log.d(TAG, "ALERT_SERVICE_UUID MATCH!");
                            break;
                        }
                    }
                } else {
                    Log.d(TAG, "No service UUIDs in advertisement");
                }
            } else {
                Log.d(TAG, "   ScanRecord is NULL");
            }

            Log.d(TAG, "   Name match: " + nameMatch + " (looking for: " + TARGET_NAME + ")");
            Log.d(TAG, "   Service match: " + serviceMatch);
            Log.d(TAG, "   Expected UUID: " + ALERT_SERVICE_UUID);

            if (nameMatch || serviceMatch) {
                Log.d(TAG, "TARGET DEVICE FOUND!");

                runOnUiThread(() -> status.setText("Device found: " + (name != null ? name : device.getAddress())));

                scanner.stopScan(this);
                Log.d(TAG, "Scan stopped");

                // Double-check permissions before connecting
                if (!hasBlePerms()) {
                    Log.e(TAG, "Lost permissions between scan and connect!");
                    runOnUiThread(() -> status.setText("Permission error - please restart app"));
                    requestBlePermsIfNeeded();
                    return;
                }

                runOnUiThread(() -> status.setText("Attempting connection..."));
                Log.d(TAG, "Calling connectGatt()...");

                connectGatt(device);

                Log.d(TAG, "connectGatt() returned");
            } else {
                Log.d(TAG, "Not target device, continuing scan");
            }
            Log.d(TAG, "-----------------------------------------------------");
        }

        @Override
        public void onScanFailed(int errorCode) {
            Log.e(TAG, "SCAN FAILED! Error code: " + errorCode);
            runOnUiThread(() -> status.setText("Scan failed: " + errorCode));
        }
    };

    @SuppressLint("MissingPermission")
    private void startScan() {
        if (!hasBlePerms()) {
            requestBlePermsIfNeeded();
            return;
        }
        if (scanner == null) {
            status.setText("Scanner unavailable");
            return;
        }
        status.setText("Scanning...");
        scanner.startScan(scanCallback);
    }

    /* Gatt connection setup*/
    @SuppressLint("MissingPermission")
    private void connectGatt(BluetoothDevice device) {

        Log.d(TAG, "Inside connectGatt() method");
        runOnUiThread(() -> status.setText("Inside connectGatt() - checking permissions..."));

        if (!hasBlePerms()) {
            Log.e(TAG, "Missing BLE permissions!");
            runOnUiThread(() -> status.setText("ERROR: Missing permissions"));
            requestBlePermsIfNeeded();
            return;
        }

        Log.d(TAG, "Permissions OK");
        runOnUiThread(() -> status.setText("Permissions OK, creating GATT connection..."));

        try {
            gatt = device.connectGatt(getApplicationContext(), false, gattCallback);

            if (gatt != null) {
                Log.d(TAG, "GATT object created successfully");
                runOnUiThread(() -> status.setText("GATT connection initiated..."));
            } else {
                Log.e(TAG, "GATT object is NULL!");
                runOnUiThread(() -> status.setText("ERROR: GATT connection failed"));
            }
        } catch (Exception e) {
            Log.e(TAG, "Exception in connectGatt: " + e.getMessage(), e);
            runOnUiThread(() -> status.setText("ERROR: " + e.getMessage()));
        }

    }

    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @SuppressLint({"SetTextI18n", "MissingPermission"})
        public void onConnectionStateChange(BluetoothGatt g, int statusGatt, int newState) {
            if (statusGatt != BluetoothGatt.GATT_SUCCESS) {
                runOnUiThread(() -> status.setText("GATT error: " + statusGatt));
                closeGatt();
                return;
            }
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                runOnUiThread(() -> status.setText("Connected. Discovering services..."));
                gatt = g;
                gatt.discoverServices();
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                runOnUiThread(() -> status.setText("Disconnected"));
                closeGatt();
            }
        }

        @SuppressLint({"SetTextI18n", "MissingPermission"})
        public void onServicesDiscovered(BluetoothGatt g, int s) {
            if (s == BluetoothGatt.GATT_SUCCESS) {
                runOnUiThread(() -> status.setText("Services discovered"));
                // list services
//                for (BluetoothGattService service : g.getServices()) {
//                    Log.d("BLE", "Service: " + service.getUuid());
//                }
            } else {
                runOnUiThread(() -> status.setText("Discovery failed (service): " + s));
            }

            // find service
            BluetoothGattService service = g.getService(ALERT_SERVICE_UUID);
            if (service == null) {
                runOnUiThread(() -> status.setText("Service not found"));
//                closeGatt();
                return;
            }
            // find characteristic
            BluetoothGattCharacteristic alertChar = service.getCharacteristic(ALERT_CHAR_UUID);
            if (alertChar == null) {
                runOnUiThread(() -> status.setText("Characteristic not found"));
//                closeGatt();
                return;
            }

            // subscribe to notifications
            // App side, ready to listen?
            boolean ready = g.setCharacteristicNotification(alertChar, true);
            if (ready) {
                runOnUiThread(() -> status.setText("Notifications enabled"));
            }

            // Pi side
            BluetoothGattDescriptor cccd = alertChar.getDescriptor(CCCD_UUID);
            if (cccd == null) {
                runOnUiThread(() -> status.setText("CCCD not found"));
                return;
            }
            cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            boolean wrote = g.writeDescriptor(cccd);
            runOnUiThread(() -> status.setText("Enabling notifications... " + wrote));


        }

        @Override
        public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor descriptor, int statusGatt) {
            super.onDescriptorWrite(g, descriptor, statusGatt);
            if (descriptor != null && CCCD_UUID.equals(descriptor.getUuid())) {
                final String msg = (statusGatt == BluetoothGatt.GATT_SUCCESS)
                        ? "Notification subscription active"
                        : ("CCCD write failed: " + statusGatt);
                runOnUiThread(() -> status.setText(msg));
            }
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic characteristic) {
            super.onCharacteristicChanged(g, characteristic);
            onCharacteristicUpdate(g, characteristic);
        }
    };

    @SuppressLint("MissingPermission")
    private void closeGatt() {
        if (gatt != null) {
            gatt.close();
            gatt = null;
        }
    }

    @SuppressLint({"SetTextI18n", "MissingPermission"})
    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        // button defined in xml
        status = findViewById(R.id.status);
        Button testAlert = findViewById(R.id.testAlert);
        scanButton = findViewById(R.id.scanNConnect);


        // for notification permission on Android 13+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ActivityCompat.requestPermissions(this,
                    new String[]{ Manifest.permission.POST_NOTIFICATIONS }, 10);
        }

        ensureNotifChannel();
        // prompt for permissions as needed
        requestBlePermsIfNeeded();

        testAlert.setOnClickListener(v -> {
            status.setText("Welcome to Handy Home Service");
            showAlert("Emergency gesture detected");
        });

        BluetoothManager nm = (BluetoothManager) getSystemService(BLUETOOTH_SERVICE);
        adapter = (nm != null) ? nm.getAdapter() : null;
        if (adapter == null || !adapter.isEnabled()) {
            status.setText("Bluetooth is not available");
        } else {
            scanner = adapter.getBluetoothLeScanner();
        }

        scanButton.setOnClickListener(v -> {status.setText("Scanning for nearby devices");
            startScan();});

        Button enableCalling = findViewById(R.id.phoneCall);
        // no phone perm check yet
//        enableCalling.setOnClickListener(v -> {
//            if (!hasPhonePermission()) {
//                Log.d(TAG, "Requesting phone permission");
//                new android.app.AlertDialog.Builder(this)
//                        .setTitle("Phone Permission Needed")
//                        .setMessage("This app needs phone permission to make emergency calls. Grant permission?")
//                        .setPositiveButton("Grant", (dialog, which) -> {
//                            ActivityCompat.requestPermissions(this,
//                                    new String[]{Manifest.permission.CALL_PHONE}, 30);
//                        })
//                        .setNegativeButton("Cancel", null)
//                        .show();
//            } else {
//                status.setText("Phone permission already granted!");
//            }
//        });
        enableCalling.setOnClickListener(v -> {status.setText("Scanning for nearby devices"); handlePhoneCall("2062014760");});

    }

    // c: data channel from pi
    // Message:
    public void onCharacteristicUpdate(BluetoothGatt g, BluetoothGattCharacteristic c) {
        if (c.getUuid().equals(ALERT_CHAR_UUID)) {
            byte[] data = c.getValue();
            String message = new String(data, StandardCharsets.UTF_8);
            runOnUiThread(() -> {
                status.setText("Alert notify: " + message);
                showAlert(message.isEmpty() ? "Emergency gesture detected" : message);
            });
            // handle message
            messageHandler(message);
        }
    }

    private void messageHandler(String message) {
        runOnUiThread(() -> {
            if (message.startsWith("CALL:")) {
                String phoneNumber = message.substring(5).trim();

//                if (hasPhonePermission()) {
//                    status.setText("Already placed a call for you");
//                 } else {
//                    handlePhoneCall(phoneNumber); // now it only opens the dialer
//                    status.setText("Open dialer");
//                }
                handlePhoneCall(phoneNumber); // now it only opens the dialer
                status.setText("Open dialer");
            }
        });

    }



    private void ensureNotifChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "Alerts", NotificationManager.IMPORTANCE_HIGH);
            NotificationManager nm = getSystemService(NotificationManager.class);
            nm.createNotificationChannel(ch);
        }
    }

    private void showAlert(String message) {
        NotificationCompat.Builder b = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_sys_warning)
                .setContentTitle("ALERT!!!")
                .setContentText(message)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setAutoCancel(true);
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        nm.notify(42, b.build());
    }

    // check for the appropriate permissions based on Android version
    private boolean hasBlePerms() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) { // Android 12+
            boolean scanPerm = ActivityCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED;
            boolean connectPerm = ActivityCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
            boolean locationPerm = ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
            boolean phonePerm = ActivityCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED;

            Log.d(TAG, "Permission check (Android 12+):");
            Log.d(TAG, "  BLUETOOTH_SCAN: " + scanPerm);
            Log.d(TAG, "  BLUETOOTH_CONNECT: " + connectPerm);
            Log.d(TAG, "  ACCESS_FINE_LOCATION: " + locationPerm);
            Log.d(TAG, "  CALL_PHONE: " + phonePerm);

            return scanPerm && connectPerm && locationPerm && phonePerm;

        } else { // Android 11 and below, the phone used is on 11
            boolean locationPerm = ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
            boolean phonePerm = ActivityCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED;

            Log.d(TAG, "Permission check (Android 11 and below):");
            Log.d(TAG, "  ACCESS_FINE_LOCATION: " + locationPerm);
            Log.d(TAG, "  CALL_PHONE: " + phonePerm);

            return locationPerm;
//            return locationPerm && phonePerm;
        }
    }

    // set a separate permission check for phone call
    private boolean hasPhonePermission() {
        boolean phonePerm = ActivityCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED;
        Log.d(TAG, "  CALL_PHONE: " + phonePerm);
        return phonePerm;
    }

    @SuppressLint("MissingPermission")
    private void handlePhoneCall(String phoneNumber) {
        // Check phone permission ONLY when calling
//        if (!hasPhonePermission()) {
//            Log.d(TAG, "Requesting CALL_PHONE permission");
//            ActivityCompat.requestPermissions(this,
//                    new String[]{Manifest.permission.CALL_PHONE}, 30);
//            return;
//        }

        // Show notification first
        showAlert("Calling " + phoneNumber);

//        try { // try DIAL for testing which open the dialer, no SIM card yet on the test phone
//            Intent dialIntent = new Intent(Intent.ACTION_DIAL);
//            dialIntent.setData(Uri.parse("tel:" + phoneNumber));
//            startActivity(dialIntent);
//        } catch (Exception e) {
//            status.setText("Failed to place call: " + e.getMessage());
//            Log.e(TAG, "Dial failed", e);
//        }

        // place the call
        try {
            Intent callIntent = new Intent(Intent.ACTION_CALL);
            callIntent.setData(Uri.parse("tel:" + phoneNumber));
            startActivity(callIntent);
        } catch (Exception e) {
            status.setText("Failed to place call: " + e.getMessage());
            Log.e(TAG, "Dial failed", e);
        }
    }

    private void requestBlePermsIfNeeded() {
        if (!hasBlePerms()) {
            Log.d(TAG, "Requesting permissions...");

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) { // Android 12+
                ActivityCompat.requestPermissions(this, new String[] {
                        Manifest.permission.BLUETOOTH_SCAN,
                        Manifest.permission.BLUETOOTH_CONNECT,
                        Manifest.permission.ACCESS_FINE_LOCATION,
                        Manifest.permission.CALL_PHONE
                }, 20);
            } else { // Android 11 and below
                ActivityCompat.requestPermissions(this, new String[] {
                        Manifest.permission.ACCESS_FINE_LOCATION,
                        Manifest.permission.ACCESS_COARSE_LOCATION,
                        Manifest.permission.CALL_PHONE,
                        Manifest.permission.BLUETOOTH,
                        Manifest.permission.BLUETOOTH_ADMIN
                }, 20);
            }

            Log.d(TAG, "Permission request dialog should appear now");
        }
    }

    // separate perm check for phone call
    private void requestPhonePermIfNeeded() {
        if (!hasPhonePermission()) {
            Log.d(TAG, "Requesting phone permission...");
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.CALL_PHONE}, 30);
        }
    }

}




















/*Src: https://github.com/lichard49/ECE475_android_tutorial/blob/main/BleTutorial/app/src/main/java/com/lichard49/bletutorial/MainActivity.java*/
//public class MainActivity extends AppCompatActivity {
//    private static final String TARGET_DEVICE = "RPi"; // pi name !!
//
//    public static final UUID UUID_SERVICE = UUID.fromString("6E400001-B5A3-F393-E0A9-E50E24DCCA9E");
//    public static final UUID UUID_TX_CHAR = UUID.fromString("6E400002-B5A3-F393-E0A9-E50E24DCCA9E");
//
//    private BluetoothLeScanner bleScanner; // for scan Pi (peripheral)
//    private BluetoothGatt bluetoothGatt; // activate GATT connection
//
//    private ScanCallback scanCallback = new ScanCallback() {
//        @Override
//        public void onScanResult(int callbackType, ScanResult result) {
//            super.onScanResult(callbackType, result);
//
//            if (TARGET_DEVICE.equals(result.getDevice().getName())) {
//                textView.setText("Connecting to: " + TARGET_DEVICE);
//
//                bleScanner.stopScan(scanCallback);
//
//                result.getDevice().connectGatt(getApplicationContext(), false, new BluetoothGattCallback() {
//                    @Override
//                    public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {
//                        runOnUiThread(() -> {
//                            textView.setText("Connected to: " + TARGET_DEVICE);
//                        });
//
//                        bluetoothGatt = gatt;
//                        bluetoothGatt.discoverServices(); // starts discovery of services
//                    }
//                });
//            }
//        }
//    };
//
//    private TextView textView;
//    private boolean ledState = true;
//
//    @Override
//    protected void onCreate(Bundle savedInstanceState) {
//        super.onCreate(savedInstanceState);
//        setContentView(R.layout.activity_main);
//
//        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) {
//            ActivityCompat.requestPermissions(this, new String[]{
//                    Manifest.permission.BLUETOOTH_SCAN,
//                    Manifest.permission.ACCESS_FINE_LOCATION,
//                    Manifest.permission.BLUETOOTH_CONNECT
//            }, 1);
//        }
//
//        BluetoothManager bluetoothManager = (BluetoothManager) getSystemService(BLUETOOTH_SERVICE);
//        BluetoothAdapter bluetoothAdapter = bluetoothManager.getAdapter();
//        bleScanner = bluetoothAdapter.getBluetoothLeScanner();
//
//        // UI setup ---
//        textView = findViewById(R.id.text);
//        Button connectButton = findViewById(R.id.connect);
//        Button sendButton = findViewById(R.id.send);
//
//        connectButton.setOnClickListener(v -> {
//            textView.setText("Scanning devices");
//            bleScanner.startScan(scanCallback);
//        });
//
//        sendButton.setOnClickListener(v -> {
//            // decide what to send
//            String text;
//            if (ledState) {
//                text = "1";
//            } else {
//                text = "0";
//            }
//            ledState = !ledState;
//
//            // send message
//            byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
//            BluetoothGattService service = bluetoothGatt.getService(UUID_SERVICE);
//            BluetoothGattCharacteristic txCharacteristic = service.getCharacteristic(UUID_TX_CHAR);
//            // set data to be written and send over BLE to the device
//            txCharacteristic.setValue(bytes);
//            txCharacteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
//            bluetoothGatt.writeCharacteristic(txCharacteristic);
//        });
//    }
//}
