import { pingPoints, batteryPoints, chartPing, chartBattery } from "./plots.js";
import {getJoystickXY, onWindowResizeNext, setIsJoystickActive, setSteerCurrent, setCruiseEnabledActive} from "./joystick_buttons.js";
import {CLIENT_ID} from "./jsmain.js";

export let controlCommandInterval = null;
export let latencyInterval = null;
export let lastChannelMessageTime = null;

let pcConnectionState = ""; // connecting->connected->disconnected->failed
let pcConnected = false;
let pcConnectionLost = false;
let pcConnectionLostChecked = false;
let pcConnectionLostTimeout = 0;
let directCtrlSendInterval = null;
let tryToRtcmInterval = null;
let tryToRtcmCount = 4;
let tryToRtcmState = "init";
let sendJoystickInProgress = false;
let sendCtrlCounter = 0;
const ALIVE_WINDOW_MS = 3000;

const CONTROL_TRANSPORT = "http"; // "http" | "dc"

let reconnectInProgress = false;
let lastReconnectAt = 0;

function clearRtcmInterval() {
  if (tryToRtcmInterval !== null) {
    clearInterval(tryToRtcmInterval);
    tryToRtcmInterval = null;
  }
}

function isPcHealthy(pc) {
  return pc && (pc.connectionState === "connected" ||
                pc.iceConnectionState === "connected" ||
                pc.iceConnectionState === "completed");
}

function isDcOpen(dc) {
  return dc && dc.readyState === "open";
}

export function onWindowResize(){
        onWindowResizeNext();
}


async function sendCtrl(cmd) {
    const resp = await fetch("/ctrl", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Client-ID": CLIENT_ID,
      "X-Client-Kind": "web",
    },
    body: JSON.stringify(cmd),
  });

  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`ctrl failed: ${resp.status} ${txt}; send cmd: ${cmd}`);
  }

  return await resp.json(); // если сервер что-то возвращает
}

async function sendJoystickDirectCtrl() {
    if (sendJoystickInProgress){
        return;
    }
    sendJoystickInProgress = true;

    const {steer_deg, accel_brake, isJoystickActive, isJoystickCruise} = getJoystickXY();
    var message = {
        type: "web_control",
        data: {
            seq: Date.now(),
            steering_angle_deg: steer_deg,
            brake_and_accel: accel_brake,
            control_enabled: isJoystickActive,
            cruise_manual_set: isJoystickCruise,
            ext_flags: [false, false, false, false]
        }
    };
    try {
        const now = new Date().getTime();
        if (!pcConnectionLost || ((now - pcConnectionLostTimeout ) < 600)){

            const result = await sendCtrl(message);
            sendCtrlCounter += 1;
            if (sendCtrlCounter % 5 === 0) {
                 pcConnectionLostChecked = false;
                if (result.ok) {
                    if ("is_master" in result) {
                        const isMaster = result["is_master"];
                        const source_control = ("source_control" in result) ? result.source_control : "NaN";
                        if (isMaster) {
                            if (source_control === "web") {
                                $("#ctrl_state").css("color", "rgb(100,204,100)").text("WEB");
                            } else if (source_control === "udp") {
                                $("#ctrl_state").css("color", "rgb(43,85,152)").text("UDP");
                            } else if (source_control === "none") {
                                $("#ctrl_state").css("color", "rgba(248,248,245,0.87)").text("OFF");
                            } else {
                                $("#ctrl_state").css("color", "rgba(255,217,0,0.87)").text(source_control);
                            }
                        } else {
                            if (source_control === "web") {
                                $("#ctrl_state").css("color", "rgb(200,0,255)").text("EXT web??");
                            } else if (source_control === "udp") {
                                $("#ctrl_state").css("color", "rgb(43,47,152)").text("UDP??");
                            } else if (source_control === "none") {
                                $("#ctrl_state").css("color", "rgba(248,248,245,0.87)").text("OFF??");
                            } else {
                                $("#ctrl_state").css("color", "rgba(255,217,0,0.87)").text(source_control + "??");
                            }
                        }
                    } else {
                        $("#ctrl_state").css("color", "rgba(255,111,0,0.9)").text("N/A");
                    }
                } else {
                    $("#ctrl_state").css("color", "rgba(255,0,0,0.88)").text("ERR");
                }
            }
        }else{
            if (!pcConnectionLostChecked) {
                pcConnectionLostChecked = true;
                $("#ctrl_state").css("color", "rgba(236,27,27,0.88)").text("LOST");
                $("#ctrl_state").css("color", "rgba(255,111,0,0.9)").text("N/A");
                setCruiseEnabledActive(false);
                setIsJoystickActive(false);
                var zero_message = {
                    type: "web_control",
                    data: {
                        seq: Date.now(),
                        steering_angle_deg: 0.0,
                        brake_and_accel: 0.0,
                        control_enabled: false,
                        cruise_manual_set: false,
                        ext_flags: [false, false, false, false]
                    }
                };
                await sendCtrl(zero_message);
            }
        }
    } catch (e) {
        console.error('sendJoystick failed:', e);

    }
    sendJoystickInProgress = false;
}

export async function offerRtcRequest(sdp, type) {
  const res = await fetch('/offer', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        "X-Client-ID": CLIENT_ID,
          "X-Client-Kind": "web",
    },
    body: JSON.stringify({ sdp: sdp, type: type })
  });
  if (!res.ok) {
       const txt = await res.text();
      throw new Error(`offer failed ${res.status}: ${txt.slice(0,400)}`);
  }
   return res;
}
//
// export function offerRtcRequest2(sdp, type) {
//   return fetch('/offer', {
//     body: JSON.stringify({sdp: sdp, type: type}),
//     headers: {'Content-Type': 'application/json'},
//     method: 'POST'
//   });
// }

export function pingHeadRequest() {
  return fetch('/', {
    method: 'HEAD',
    headers: {
      "Content-Type": "application/json",
      "X-Client-ID": CLIENT_ID,
      "X-Client-Kind": "web",
    },
  });
}


export function createPeerConnection(pc) {
  var config = {
    sdpSemantics: 'unified-plan'
  };

  pc = new RTCPeerConnection(config);

  const videoEl = document.getElementById('video');
  videoEl.autoplay = true;
  videoEl.muted = true;
  videoEl.playsInline = true;
  videoEl.addEventListener("stalled", () => console.log("VIDEO stalled"));
  videoEl.addEventListener("pause", () => console.log("VIDEO paused"));

  pc.addEventListener('track', (evt) => {
      console.log("[VIDEO] Adding Tracks!", evt.track.kind, evt.streams);
      if (evt.track.kind === 'video') {
        try {
          let stream = evt.streams && evt.streams[0];
          if (!stream) stream = new MediaStream([evt.track]);

          // Установите srcObject ДО попытки play()
          console.log('[VIDEO] attaching new stream to video element');
          videoEl.srcObject = stream;

          // Ждем когда видео будет готово
          videoEl.onloadedmetadata = async () => {
            try {
              await videoEl.play();
              console.log("[VIDEO] Video playback started successfully");
              tryToRtcmState = "success"
            } catch (e) {
              console.warn('[VIDEO] video.play() blocked:', e);
              // Попробуем снова через небольшую задержку
              setTimeout(async () => {
                try {
                  await videoEl.play();
                } catch (e2) {
                  console.warn('[VIDEO] Second video.play() attempt failed:', e2);
                }
              }, 100);
            }
          };

        } catch (e) {
          console.log("[VIDEO] Error attaching video track:", e);

        }
      } else {
        console.log("[VIDEO] Received non-video track:", evt.track.kind);
      }
    });

  pc.addEventListener("iceconnectionstatechange", () => {
    console.log("ICE:", pc.iceConnectionState);
  });
  pc.addEventListener("connectionstatechange", () => {
      console.log("PC:", pc.connectionState);
      // connecting->connected->disconnected->failed
      if (pc.connectionState === "connected"){
           pcConnectionLost = false;
          pcConnected = true;
      }else if ( pc.connectionState === "failed"){
          pcConnected = false;
          pcConnectionLostTimeout = new Date().getTime();
          pcConnectionLost = true;
      }
      pcConnectionState = pc.connectionState;
  });

  return pc;
}

export function negotiate(pc, iceRestart = false) {
    if (pc.signalingState !== "stable") {
        return Promise.resolve(); // не лезем в переговоры в нестабильном состоянии
    }

    return pc.createOffer({offerToReceiveVideo:true, iceRestart})
      .then(function(offer) { return pc.setLocalDescription(offer);  })
      .then(function() {
          return new Promise( function(resolve) {
              if (pc.iceGatheringState === 'complete') { resolve();  }
              else {
                function checkState() {
                  if (pc.iceGatheringState === 'complete') {
                    pc.removeEventListener('icegatheringstatechange', checkState);
                    resolve();
                  }
                }
                pc.addEventListener('icegatheringstatechange', checkState);
              }
          });
      }) .then(function() {
            var offer = pc.localDescription;
            console.log("Sending offer: ", offer);
            return offerRtcRequest(offer.sdp, offer.type);
      })
      .then(response => response.json())
      .then(answer => pc.setRemoteDescription(answer));
      //   .then(function(response) {
      //   console.log(response);
      //   return response.json();
      // }).then(function(answer) {
      //   return pc.setRemoteDescription(answer);
      // });
}


export function start(pc, dc) {
    pc = createPeerConnection(pc);

  try {
    pc.addTransceiver('video', { direction: 'recvonly' });
  } catch (e) {
    console.error('addTransceiver video failed:', e);
  }

  var parameters = {"ordered": true};
  dc = pc.createDataChannel('data', parameters);
  dc.onclose = function() {
      console.error('DataChannel close:');
      if (controlCommandInterval!==null){
        clearInterval(controlCommandInterval);
      }
     if (latencyInterval!==null){
        clearInterval(latencyInterval);
     }
     if (directCtrlSendInterval!==null){
        clearInterval(directCtrlSendInterval);
     }
  };

  dc.addEventListener("close", () => console.log("DC closed"));
  dc.addEventListener("error", (e) => console.log("DC error", e));


  function sendJoystickOverDataChannel() {
    const {steer_deg, accel_brake, isJoystickActive ,isJoystickCruise} = getJoystickXY();
    let buttons = [true, isJoystickActive, isJoystickCruise, false, false, false, false];
    var message = JSON.stringify({type: "testJoystick", data: {axes: [steer_deg, accel_brake], buttons: buttons}})
    dc.send(message);
  }

  function checkLatency() {
    const initialTime = new Date().getTime();
    pingHeadRequest().then(function() {
      const currentTime = new Date().getTime();
      const age = lastChannelMessageTime ? (currentTime - lastChannelMessageTime) : Infinity;

      if (Math.abs(age) < ALIVE_WINDOW_MS) {
        const pingtime = currentTime - initialTime;
        pingPoints.push({'x': currentTime, 'y': pingtime});
        if (pingPoints.length > 1000) {
          pingPoints.shift();
        }
        chartPing.update();
        $("#ping-time").css("color", "rgba(248,248,245,0.87)").text((pingtime) + "мс");
      }else {
        $("#ping-time").css("color", "rgba(234,66,66,0.87)").text( "н/д");
      }
    })
  }

  dc.onopen = function() {
      console.warn('DataChannel onopen:');
      if (controlCommandInterval!==null){
        clearInterval(controlCommandInterval);
      }
     if (latencyInterval!==null){
        clearInterval(latencyInterval);
     }
     if (CONTROL_TRANSPORT === "dc"){
         controlCommandInterval = setInterval(sendJoystickOverDataChannel, 50);
         sendJoystickOverDataChannel();
     }
     if (latencyInterval!==null){
         clearInterval(latencyInterval);
     }
     latencyInterval = setInterval(checkLatency, 1000);
  };

  const textDecoder = new TextDecoder();
  var carStaterIndex = 0;
  dc.onmessage = function(evt) {
    const text = textDecoder.decode(evt.data);
    const msg = JSON.parse(text);

    if (msg.type === 'carState') {
        if (carStaterIndex % 50 == 0) {
            const batteryLevel = Math.round(msg.data.fuelGauge * 100);
            $("#battery").text(batteryLevel + "%");
            batteryPoints.push({'x': new Date().getTime(), 'y': batteryLevel});
            if (batteryPoints.length > 1000) {
                batteryPoints.shift();
            }
            chartBattery.update();

            const curSpeed = Math.round(msg.data.vEgo * 3.6); // m/s to km/h
            $("#speed").text(curSpeed + " km/h");
        }

        if (carStaterIndex % 200 == 0) {
            if (msg.data.cruiseState.available) {
                if (msg.data.cruiseState.enabled) {
                    $("#cruise").text('АВТОПИЛОТ:ON');
                    setCruiseEnabledActive(true);
                } else {
                    $("#cruise").text("АВТОПИЛОТ:OFF");
                    setCruiseEnabledActive(false);
                }
            } else {
                $("#cruise").text("АВТОПИЛОТ:NAN");
                setCruiseEnabledActive(false);
            }
        }
        setSteerCurrent(msg.data.steeringAngleDeg);
    }

    carStaterIndex += 1;
    lastChannelMessageTime = new Date().getTime();
    $(".pre-blob").addClass('blob');
  };


  if (CONTROL_TRANSPORT === "http"){
      if (directCtrlSendInterval!==null){
            clearInterval(directCtrlSendInterval);
      }
      directCtrlSendInterval = setInterval(sendJoystickDirectCtrl, 50);
      sendJoystickDirectCtrl();
  }

  function tryToRtcmSend2(){
      const now = Date.now();
      // Если уже всё хорошо — прекращаем цикл
      if (isPcHealthy(pc) && isDcOpen(dc)) {
        if (tryToRtcmState !== "wait_for_lost") {
          console.log("RTCM via DataChannel connected successfully.");
          tryToRtcmState = "wait_for_lost";
        }
        // clearRtcmInterval();
        return;
      }
      // Троттлинг, чтобы не запускать переговоры слишком часто
      if (reconnectInProgress) return;
      // if (now - lastReconnectAt < 2500) return;
      //
      //  else if (tryToRtcmState === "wait_for_lost") {
      //     if (){
      //         tryToRtcmCount = 4;
      //     }else{
      //         return;
      //     }
      // }
      // Если попытки кончились — останавливаем
      if (tryToRtcmCount <= 0) {
        clearRtcmInterval();
        console.error("RTCM reconnect attempts exhausted");
        return;
      }
      // Если connectionState failed/disconnected — делаем ICE restart
      const needIceRestart = (pc.iceConnectionState === "failed" || pc.iceConnectionState === "disconnected");

      console.log("Trying to reconnect WebRTC, attempts left:", tryToRtcmCount, "iceRestart=", needIceRestart);

      reconnectInProgress = true;
      lastReconnectAt = now;
      tryToRtcmState = "sending";

      negotiate(pc, needIceRestart)
        .then(() => {
          tryToRtcmState = "init";
        })
        .catch((err) => {
          console.error("negotiate error:", String(err).slice(0, 400));
          tryToRtcmCount -= 1;
          tryToRtcmState = "error";
        })
        .finally(() => {
          reconnectInProgress = false;
        });
    }

    function tryToRtcmSend2(){
      if (tryToRtcmCount > 0){
          //pcConnectionState = "";  connecting->connected->disconnected->failed
          if (tryToRtcmState === "sending"){
              return;
          }else if (tryToRtcmState === "success"){
              // if (tryToRtcmInterval !== null){
              //     clearInterval(tryToRtcmInterval);
              //     tryToRtcmInterval = null;
              // }
              if (pcConnected) {
                  console.log("RTCM via DataChannel connected successfully.");
                  tryToRtcmCount = 4;
                  tryToRtcmState = "wait_for_lost";
              }
              return;
          } else if (tryToRtcmState === "wait_for_lost"){
              if (!pcConnected) {
                  console.log("RTCM via DataChannel lost connected. Try to reconnect.");
                  tryToRtcmCount = 4;
              } else {
                  return;
              }
          }
          console.log("Trying to send RTCM via DataChannel, attempts left:", tryToRtcmCount);
          tryToRtcmState = "sending";
          negotiate(pc)
                .catch(function (err) {
                  const  err_msg = err.toString().slice(0,400);
                  console.error('negotiate error:', err_msg);
                  tryToRtcmState = "error";
                  tryToRtcmCount -= 1;
                  if (tryToRtcmCount <= 0){
                      if (tryToRtcmInterval !== null){
                        clearInterval(tryToRtcmInterval);
                        tryToRtcmInterval = null;
                      }

                      alert('Negotiation RTCM offer failed: ' + err_msg);
                        // throw new Error(`offer failed ${err}: ${txt.slice(0,400)}`);
                  }
                });

      } else {
           if (tryToRtcmInterval !== null){
               clearInterval(tryToRtcmInterval);
               tryToRtcmInterval = null;
           }
      }
  }

  // Попытаться отправить RTCM запрос несколько раз
  tryToRtcmCount = 4;
   if (tryToRtcmInterval !== null){
       clearInterval(tryToRtcmInterval);
   }
  tryToRtcmInterval = setInterval(tryToRtcmSend, 2000);
  tryToRtcmSend();

  return { pc, dc };
}


/*
struct CarState {
  # CAN health
  canValid @26 :Bool;       # invalid counter/checksums
  canTimeout @40 :Bool;     # CAN bus dropped out
  canErrorCounter @48 :UInt32;

  # process meta
  cumLagMs @50 :Float32;

  # car speed
  vEgo @1 :Float32;            # best estimate of speed
  aEgo @16 :Float32;           # best estimate of aCAN cceleration
  vEgoRaw @17 :Float32;        # unfiltered speed from wheel speed sensors
  vEgoCluster @44 :Float32;    # best estimate of speed shown on car's instrument cluster, used for UI

  vCruise @53 :Float32;        # actual set speed
  vCruiseCluster @54 :Float32; # set speed to display in the UI

  yawRate @22 :Float32;     # best estimate of yaw rate
  standstill @18 :Bool;
  wheelSpeeds @2 :WheelSpeeds;

  gasPressed @4 :Bool;    # this is user pedal only

  # brake pedal, 0.0-1.0
  brake @5 :Float32;      # this is user pedal only
  brakePressed @6 :Bool;  # this is user pedal only
  regenBraking @45 :Bool; # this is user pedal only
  parkingBrake @39 :Bool;
  brakeHoldActive @38 :Bool;

  # steering wheel
  steeringAngleDeg @7 :Float32;
  steeringAngleOffsetDeg @37 :Float32; # Offset between sensors in case there multiple
  steeringRateDeg @15 :Float32;    # optional
  steeringTorque @8 :Float32;      # Native CAN units, only needed on cars where it's used for control
  steeringTorqueEps @27 :Float32;  # Native CAN units, only needed on cars where it's used for control
  steeringPressed @9 :Bool;        # is the user overring the steering wheel?
  steeringDisengage @58 :Bool;     # more force than steeringPressed, disengages for applicable brands
  steerFaultTemporary @35 :Bool;
  steerFaultPermanent @36 :Bool;

  invalidLkasSetting @55 :Bool;    # stock LKAS is incorrectly configured (i.e. on or off)
  stockAeb @30 :Bool;
  stockLkas @59 :Bool;
  stockFcw @31 :Bool;
  espDisabled @32 :Bool;
  accFaulted @42 :Bool;
  carFaultedNonCritical @47 :Bool;  # some ECU is faulted, but car remains controllable
  espActive @51 :Bool;
  vehicleSensorsInvalid @52 :Bool;  # invalid steering angle readings, etc.
  lowSpeedAlert @56 :Bool;  # lost steering control due to a dynamic min steering speed
  blockPcmEnable @60 :Bool;  # whether to allow PCM to enable this frame

  # cruise state
  cruiseState @10 :CruiseState;

  # gear
  gearShifter @14 :GearShifter;

  # button presses
  buttonEvents @11 :List(ButtonEvent);
  buttonEnable @57 :Bool;  # user is requesting enable, usually one frame. set if pcmCruise=False
  leftBlinker @20 :Bool;
  rightBlinker @21 :Bool;
  genericToggle @23 :Bool;

  # lock info
  doorOpen @24 :Bool;           # ideally includes all doors
  seatbeltUnlatched @25 :Bool;  # driver seatbelt

  # blindspot sensors
  leftBlindspot @33 :Bool;  # Is there something blocking the left lane change
  rightBlindspot @34 :Bool; # Is there something blocking the right lane change

  fuelGauge @41 :Float32; # battery or fuel tank level from [0.0, 1.0]
  charging @43 :Bool;

  struct WheelSpeeds {
    # optional wheel speeds
    fl @0 :Float32;
    fr @1 :Float32;
    rl @2 :Float32;
    rr @3 :Float32;
  }

  struct CruiseState {
    enabled @0 :Bool;
    speed @1 :Float32;
    speedCluster @6 :Float32;  # Set speed as shown on instrument cluster
    available @2 :Bool;
    standstill @4 :Bool;
    nonAdaptive @5 :Bool;

    speedOffsetDEPRECATED @3 :Float32;
  }

  enum GearShifter {
    unknown @0;
    park @1;
    drive @2;
    neutral @3;
    reverse @4;
    sport @5;
    low @6;
    brake @7;
    eco @8;
    manumatic @9;
  }

  # send on change
  struct ButtonEvent {
    pressed @0 :Bool;
    type @1 :Type;

    enum Type {
      unknown @0;
      leftBlinker @1;
      rightBlinker @2;
      accelCruise @3;
      decelCruise @4;
      cancel @5;
      lkas @6;
      altButton2 @7;
      mainCruise @8;
      setCruise @9;
      resumeCruise @10;
      gapAdjustCruise @11;
    }
  }
}
 */
export function stop(pc, dc) {
  console.log("stop pc", pc);
  if (dc) {
    dc.close();
  }
  if (pc.getTransceivers) {
    pc.getTransceivers().forEach(function(transceiver) {
      if (transceiver.stop) {
        transceiver.stop();
      }
    });
  }
  pc.getSenders().forEach(function(sender) {
    sender.track.stop();
  });
  setTimeout(function() {
    pc.close();
  }, 500);
  if (controlCommandInterval!==null){
    clearInterval(controlCommandInterval);
  }
  if (latencyInterval!==null){
    clearInterval(latencyInterval);
  }
  if (directCtrlSendInterval!==null){
    clearInterval(directCtrlSendInterval);
  }
}
