var BLE_TIMEOUT = 10000;
var TARGET_UUID = "0000110A-0000-1000-8000-00805F9B34FB";
var devices = [];

function startScan() {
    print("Demarrage du scan Bluetooth");
    devices = [];

    ble.startScan({
        onFound: function(device) {
            if (!device) return;

            if (device.services &&
                device.services.indexOf(TARGET_UUID) >= 0) {

                devices.push({
                    name: device.name ? device.name : "Inconnu",
                    address: device.address ? device.address : "Inconnue",
                    uuid: device.uuid ? device.uuid : "Aucun UUID",
                    rssi: device.rssi ? device.rssi : 0
                });

                print("Trouve : " + (device.name ? device.name : "Inconnu"));
            }
        },

        onTimeout: function() {
            showDevices();
        },

        onError: function(err) {
            print("Erreur scan : " + err);
        }
    });

    setTimeout(function() {
        ble.stopScan();
    }, BLE_TIMEOUT);
}

function showDevices() {
    var output;
    var i;

    if (devices.length === 0) {
        print("Aucun appareil trouve");
        return;
    }

    output = "Appareils trouves :\n\n";

    for (i = 0; i < devices.length; i++) {
        output += (i + 1) + ". " + devices[i].name + "\n";
        output += "Adresse : " + devices[i].address + "\n";
        output += "UUID : " + devices[i].uuid + "\n";
        output += "RSSI : " + devices[i].rssi + "\n\n";
    }

    print(output);
}

startScan();