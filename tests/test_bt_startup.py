"""Compile the actual Bluetooth adapter against a fake SDK; test HAL linking,
startup failures and bounded receive bursts. This does not emulate Bluetooth hardware."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = r'''
#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>
#define CONFIG_BT_SPP_ENABLED 1
#define CONFIG_BT_ACL_CONNECTIONS 4
#define BTDM_CONTROLLER_BR_EDR_MAX_ACL_CONN_LIMIT 7
#define ESP_OK 0
#define ESP_ERR_NO_MEM 0x101
#define ESP_ERR_INVALID_STATE 0x103
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define INPUT_PULLUP 1
#define LOW 0
#define pdTRUE 1
#define pdFALSE 0
#define pdMS_TO_TICKS(x) (x)
using esp_err_t = int;
using EventBits_t = unsigned;
using QueueHandle_t = void*;
using EventGroupHandle_t = void*;
using esp_bt_mode_t = int;
constexpr int ESP_BT_MODE_BLE=1, ESP_BT_MODE_CLASSIC_BT=2, ESP_BT_MODE_BTDM=3;
constexpr int ESP_BT_CONTROLLER_STATUS_IDLE=0, ESP_BT_CONTROLLER_STATUS_ENABLED=2;
struct esp_bt_controller_config_t { int mode; uint8_t bt_max_acl_conn; };
#define BT_CONTROLLER_INIT_CONFIG_DEFAULT() esp_bt_controller_config_t{ESP_BT_MODE_BTDM, 2}
using esp_spp_cb_event_t = int;
constexpr int ESP_SPP_INIT_EVT=0, ESP_SPP_START_EVT=1, ESP_SPP_SRV_OPEN_EVT=2, ESP_SPP_DATA_IND_EVT=3, ESP_SPP_WRITE_EVT=4, ESP_SPP_CONG_EVT=5, ESP_SPP_CLOSE_EVT=6;
constexpr int ESP_SPP_SUCCESS=0, ESP_SPP_SEC_AUTHENTICATE=2, ESP_SPP_SEC_ENCRYPT=4, ESP_SPP_ROLE_SLAVE=1, ESP_SPP_MODE_CB=0;
struct esp_spp_cb_param_t {
    struct { int status; } init{}, start{};
    struct { int status; uint32_t handle; } srv_open{};
    struct { uint32_t handle; size_t len; uint8_t* data; } data_ind{};
    struct { uint32_t handle; bool cong; int status; } write{};
    struct { uint32_t handle; bool cong; } cong{};
    struct { uint32_t handle; } close{};
};
using esp_bt_gap_cb_event_t = int;
constexpr int ESP_BT_GAP_CFM_REQ_EVT=1, ESP_BT_GAP_PIN_REQ_EVT=2, ESP_BT_GAP_AUTH_CMPL_EVT=3;
constexpr int ESP_BT_IO_CAP_IO=1, ESP_BT_SP_IOCAP_MODE=1, ESP_BT_CONNECTABLE=1, ESP_BT_GENERAL_DISCOVERABLE=1, ESP_BT_STATUS_SUCCESS=0;
using esp_bt_pin_code_t = uint8_t[16];
struct esp_bt_gap_cb_param_t {
    struct { uint8_t bda[6]; uint32_t num_val; } cfm_req{};
    struct { uint8_t bda[6]; } pin_req{};
    struct { int stat; } auth_cmpl{};
};
struct SerialPort { void println(const char*); void printf(const char*,...); int available(); int read(); };
extern SerialPort Serial;
void pinMode(int,int); int digitalRead(int); uint32_t millis();
QueueHandle_t xQueueCreate(unsigned,size_t); void xQueueReset(QueueHandle_t);
int xQueueSend(QueueHandle_t,const void*,unsigned); int xQueueReceive(QueueHandle_t,void*,unsigned); unsigned uxQueueMessagesWaiting(QueueHandle_t);
EventGroupHandle_t xEventGroupCreate(); void xEventGroupClearBits(EventGroupHandle_t,EventBits_t); void xEventGroupSetBits(EventGroupHandle_t,EventBits_t);
EventBits_t xEventGroupWaitBits(EventGroupHandle_t,EventBits_t,int,int,unsigned);
extern "C" bool btStarted();
extern "C" bool btInUse();
int esp_bt_controller_get_status(); size_t esp_get_free_heap_size(); size_t heap_caps_get_largest_free_block(unsigned);
const char* esp_err_to_name(esp_err_t);
esp_err_t esp_bt_controller_mem_release(int); esp_err_t esp_bt_controller_init(esp_bt_controller_config_t*); esp_err_t esp_bt_controller_enable(int);
esp_err_t esp_bluedroid_init(); esp_err_t esp_bluedroid_enable();
esp_err_t esp_bt_gap_register_callback(void(*)(esp_bt_gap_cb_event_t,esp_bt_gap_cb_param_t*));
esp_err_t esp_spp_register_callback(void(*)(esp_spp_cb_event_t,esp_spp_cb_param_t*));
esp_err_t esp_bt_gap_set_security_param(int,void*,size_t); esp_err_t esp_spp_init(int);
esp_err_t esp_bt_dev_set_device_name(const char*); esp_err_t esp_bt_gap_set_scan_mode(int,int);
esp_err_t esp_spp_start_srv(int,int,int,const char*); esp_err_t esp_spp_disconnect(uint32_t);
esp_err_t esp_bt_gap_ssp_confirm_reply(uint8_t*,bool); esp_err_t esp_bt_gap_pin_reply(uint8_t*,bool,int,uint8_t*);
esp_err_t esp_spp_write(uint32_t,size_t,uint8_t*);
'''
MOCK = r'''
#include "BwwBluetooth.h"
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>
#include <iostream>
#include <cstdlib>
#include <deque>
SerialPort Serial;
std::string fail, logs;
std::vector<std::string> calls;
void(*spp)(esp_spp_cb_event_t,esp_spp_cb_param_t*)=nullptr;
struct Queue { unsigned capacity; std::deque<uint8_t> bytes; };
BwwBluetooth* reader=nullptr;
bool draining=true;
unsigned waits=0;
uint32_t clockNow=0, waitCost=1;
std::vector<unsigned> waitBudgets;
std::vector<uint32_t> disconnected;
std::vector<uint8_t> received[3];
void ensure(bool);
void drainReceivers(){
    for(size_t slot=0;slot<3;++slot) for(unsigned n=0;n<512;++n){
        int byte=reader->read(slot,reader->clientHandle(slot));
        if(byte<0)break;
        received[slot].push_back(static_cast<uint8_t>(byte));
    }
}
void SerialPort::println(const char* s){logs+=s; logs+='\n';}
void SerialPort::printf(const char* format,...){char buffer[512];va_list args;va_start(args,format);vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);logs+=buffer;}
int SerialPort::available(){return 0;} int SerialPort::read(){return -1;}
void pinMode(int,int){} int digitalRead(int){return 1;} uint32_t millis(){return clockNow;}
QueueHandle_t xQueueCreate(unsigned capacity,size_t){return fail=="client queue/event allocation"?nullptr:new Queue{capacity,{}};}
void xQueueReset(QueueHandle_t q){static_cast<Queue*>(q)->bytes.clear();}
int xQueueSend(QueueHandle_t q,const void* data,unsigned timeout){
    auto& queue=*static_cast<Queue*>(q);
    if(queue.bytes.size()==queue.capacity){
        if(!timeout)return pdFALSE;
        ensure(timeout<=2000);++waits;waitBudgets.push_back(timeout);
        clockNow+=waitCost<timeout?waitCost:timeout;
        if(draining && waitCost<=timeout)drainReceivers();
        if(queue.bytes.size()==queue.capacity)return pdFALSE;
    }
    queue.bytes.push_back(*static_cast<const uint8_t*>(data));return pdTRUE;
}
int xQueueReceive(QueueHandle_t q,void* out,unsigned){
    auto& bytes=static_cast<Queue*>(q)->bytes;
    if(bytes.empty())return pdFALSE;
    *static_cast<uint8_t*>(out)=bytes.front();bytes.pop_front();return pdTRUE;
}
unsigned uxQueueMessagesWaiting(QueueHandle_t q){return static_cast<Queue*>(q)->bytes.size();}
EventGroupHandle_t xEventGroupCreate(){return reinterpret_cast<void*>(2);}
void xEventGroupClearBits(EventGroupHandle_t,EventBits_t){} void xEventGroupSetBits(EventGroupHandle_t,EventBits_t){}
EventBits_t xEventGroupWaitBits(EventGroupHandle_t,EventBits_t,int,int,unsigned){return 0;}
// Models initArduino's weak definition. The strong definition lives in the HAL
// archive and is pulled in only by an actual adapter reference to btStarted().
extern "C" __attribute__((weak)) bool btInUse(){return false;}
int esp_bt_controller_get_status(){return ESP_BT_CONTROLLER_STATUS_IDLE;}
size_t esp_get_free_heap_size(){return 200000;} size_t heap_caps_get_largest_free_block(unsigned){return 120000;}
const char* esp_err_to_name(esp_err_t e){return e==ESP_ERR_NO_MEM?"ESP_ERR_NO_MEM":"ESP_ERR_INVALID_STATE";}
void ensure(bool condition){if(!condition){std::cerr<<"Assertion failed. Log:\n"<<logs;std::exit(1);}}
esp_err_t step(const char* name){calls.push_back(name);return fail==name?ESP_ERR_INVALID_STATE:ESP_OK;}
esp_err_t esp_bt_controller_mem_release(int mode){ensure(mode==ESP_BT_MODE_BLE);return step("release unused BLE memory");}
esp_err_t esp_bt_controller_init(esp_bt_controller_config_t* cfg){ensure(btInUse());ensure(cfg->mode==ESP_BT_MODE_CLASSIC_BT);ensure(cfg->bt_max_acl_conn==3);return step("esp_bt_controller_init");}
esp_err_t esp_bt_controller_enable(int mode){ensure(mode==ESP_BT_MODE_CLASSIC_BT);return step("esp_bt_controller_enable");}
esp_err_t esp_bluedroid_init(){return step("esp_bluedroid_init");} esp_err_t esp_bluedroid_enable(){return step("esp_bluedroid_enable");}
esp_err_t esp_bt_gap_register_callback(void(*)(esp_bt_gap_cb_event_t,esp_bt_gap_cb_param_t*)){return step("esp_bt_gap_register_callback");}
esp_err_t esp_spp_register_callback(void(*callback)(esp_spp_cb_event_t,esp_spp_cb_param_t*)){spp=callback;return step("esp_spp_register_callback");}
esp_err_t esp_bt_gap_set_security_param(int,void*,size_t size){ensure(size==1);return step("esp_bt_gap_set_security_param");}
esp_err_t esp_spp_init(int mode){ensure(mode==ESP_SPP_MODE_CB);return step("esp_spp_init");}
esp_err_t esp_bt_dev_set_device_name(const char* name){ensure(std::string(name)=="BWW-ESP32");return step("esp_bt_dev_set_device_name");}
esp_err_t esp_bt_gap_set_scan_mode(int,int){return step("esp_bt_gap_set_scan_mode");}
esp_err_t esp_spp_start_srv(int security,int,int,const char*){ensure(security==(ESP_SPP_SEC_AUTHENTICATE|ESP_SPP_SEC_ENCRYPT));return step("esp_spp_start_srv");}
esp_err_t esp_spp_disconnect(uint32_t handle){disconnected.push_back(handle);return ESP_OK;} esp_err_t esp_bt_gap_ssp_confirm_reply(uint8_t*,bool){return ESP_OK;}
esp_err_t esp_bt_gap_pin_reply(uint8_t*,bool,int,uint8_t*){return ESP_OK;} esp_err_t esp_spp_write(uint32_t,size_t,uint8_t*){return ESP_OK;}
int main(int argc,char**argv){
    fail=argc>1?argv[1]:"";
    // This check happens before setup/begin, just like Arduino's memory-release
    // decision. It fails if the adapter stops linking the HAL object.
    ensure(btInUse());
    BwwBluetooth bluetooth;
    bool result=bluetooth.begin("BWW-ESP32");
    bool async=fail=="esp_bt_dev_set_device_name"||fail=="esp_bt_gap_set_scan_mode"||fail=="esp_spp_start_srv";
    if(fail.empty()||async){
        ensure(result); ensure(calls.size()==9); ensure(spp!=nullptr);
        esp_spp_cb_param_t param; param.init.status=ESP_SPP_SUCCESS;spp(ESP_SPP_INIT_EVT,&param);
    }else ensure(!result);
    if(!fail.empty()){
        ensure(logs.find(fail)!=std::string::npos);
        ensure(logs.find(fail=="client queue/event allocation"?"ESP_ERR_NO_MEM":"ESP_ERR_INVALID_STATE")!=std::string::npos);
        ensure(logs.find("Free heap=")!=std::string::npos);
        if(fail!="client queue/event allocation")ensure(calls.back()==fail);
    }else {
        ensure(calls.size()==12);reader=&bluetooth;
        std::vector<uint8_t> expected[3];
        for(size_t slot=0;slot<3;++slot){
            esp_spp_cb_param_t event;event.srv_open.status=ESP_SPP_SUCCESS;event.srv_open.handle=31+slot;
            spp(ESP_SPP_SRV_OPEN_EVT,&event);
            for(unsigned n=0;n<16480;++n)expected[slot].push_back(static_cast<uint8_t>(n+slot*71));
        }
        // Interleave complete upload-size bursts into bounded queues. The fake
        // main task drains bytes only when a blocking send yields to it.
        for(unsigned part=0;part<2;++part)for(size_t slot=0;slot<3;++slot){
            esp_spp_cb_param_t event;event.data_ind.handle=31+slot;
            event.data_ind.data=expected[slot].data()+part*8240;event.data_ind.len=8240;
            spp(ESP_SPP_DATA_IND_EVT,&event);
        }
        while(bluetooth.available(0)||bluetooth.available(1)||bluetooth.available(2))drainReceivers();
        ensure(waits>0 && disconnected.empty());
        for(size_t slot=0;slot<3;++slot)ensure(received[slot]==expected[slot]);
        // A genuinely stalled reader still fails boundedly, only on its client.
        draining=false;esp_spp_cb_param_t event;event.data_ind.handle=32;
        event.data_ind.data=expected[1].data();event.data_ind.len=5000;
        spp(ESP_SPP_DATA_IND_EVT,&event);
        ensure(disconnected.size()==1 && disconnected[0]==32);
        ensure(logs.find("Bluetooth receive stalled")!=std::string::npos);
        // Slow progress must not reset the total indication deadline per byte.
        draining=true;waitCost=350;waitBudgets.clear();uint32_t started=clockNow;
        event.data_ind.handle=33;event.data_ind.data=expected[2].data();event.data_ind.len=16480;
        spp(ESP_SPP_DATA_IND_EVT,&event);
        ensure(disconnected.size()==2 && disconnected[1]==33);
        ensure(clockNow-started==2000 && waitBudgets.front()==2000 && waitBudgets.back()<350);
    }
    return 0;
}
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'esp32/src/BwwBluetooth.cpp')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='bww-bt-startup-') as temporary:
        folder=Path(temporary); (folder/'Platform.h').write_text(PLATFORM)
        headers=['Arduino.h','esp_bt.h','esp_bt_main.h','esp_bt_device.h','esp_system.h','esp32-hal-bt.h',
                 'esp_heap_caps.h','esp_err.h','esp_spp_api.h','esp_gap_bt_api.h',
                 'freertos/FreeRTOS.h','freertos/queue.h','freertos/event_groups.h']
        for name in headers:
            path=folder/name;path.parent.mkdir(exist_ok=True);path.write_text('#include "Platform.h"\n')
        (folder/'mock.cpp').write_text(MOCK)
        (folder/'hal.cpp').write_text('extern "C" bool btInUse(){return true;}\nextern "C" bool btStarted(){return false;}\n')
        flags=['g++','-std=c++17','-Wall','-Wextra','-Werror','-flto','-ffunction-sections','-fdata-sections']
        subprocess.run(flags+['-c',str(folder/'hal.cpp'),'-o',str(folder/'hal.o')],check=True)
        subprocess.run(['ar','rcs',str(folder/'hal.a'),str(folder/'hal.o')],check=True)
        executable=str(folder/'startup')
        subprocess.run(flags+['-I'+str(folder),'-I'+str(ROOT/'esp32/include'),str(args.source),str(folder/'mock.cpp'),
                              str(folder/'hal.a'),'-Wl,--gc-sections','-o',executable],check=True)
        failures=['client queue/event allocation','release unused BLE memory','esp_bt_controller_init','esp_bt_controller_enable',
                  'esp_bluedroid_init','esp_bluedroid_enable','esp_bt_gap_register_callback','esp_spp_register_callback',
                  'esp_bt_gap_set_security_param','esp_spp_init','esp_bt_dev_set_device_name','esp_bt_gap_set_scan_mode','esp_spp_start_srv']
        for failure in ['']+failures:subprocess.run([executable,failure],check=True)
        print('Bluetooth adapter: HAL retained; secure 3-client startup, 13 failure diagnostics, lossless 16 KiB interleaved receive bursts and bounded stalled-reader handling passed (fake SDK).')

if __name__=='__main__':main()
