import { getXY } from "./controls.js";
import { pingPoints, batteryPoints, chartPing, chartBattery } from "./plots.js";
import {getJoystickXY, onWindowResizeNext, setSteerMaxRotationAngle, setSteerCurrent, setCruiseEnabledActive} from "./joystick_buttons.js";

export let controlCommandInterval = null;
export let latencyInterval = null;
export let lastChannelMessageTime = null;

export function onWindowResize(){
        onWindowResizeNext();
}

export async function offerRtcRequest(sdp, type) {
  const res = await fetch('/offer', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ sdp: sdp, type: type })
  });
  if (!res.ok) {
       const txt = await res.text();
      throw new Error(`offer failed ${res.status}: ${txt.slice(0,400)}`);
  }
   return res;
}

export function offerRtcRequest2(sdp, type) {
  return fetch('/offer', {
    body: JSON.stringify({sdp: sdp, type: type}),
    headers: {'Content-Type': 'application/json'},
    method: 'POST'
  });
}

export function pingHeadRequest() {
  return fetch('/', {
    method: 'HEAD'
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

  return pc;
}

export function negotiate(pc) {
  return pc.createOffer({offerToReceiveVideo:true}).then(function(offer) {
    return pc.setLocalDescription(offer);
  }).then(function() {
    return new Promise(function(resolve) {
      if (pc.iceGatheringState === 'complete') {
        resolve();
      }
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
  }).then(function() {
    var offer = pc.localDescription;
    console.log("Sending offer: ", offer);
    return offerRtcRequest(offer.sdp, offer.type);
  }).then(function(response) {
    console.log(response);
    return response.json();
  }).then(function(answer) {
    return pc.setRemoteDescription(answer);
  }).catch(function(e) {
    alert(e);
  });
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
  };

  function sendJoystickOverDataChannel() {
    const {steer_deg, accel_brake, isJoystickActive ,isJoystickCruise} = getJoystickXY();
    let buttons = [true, false, isJoystickActive, isJoystickCruise, false, false, false, false];
    var message = JSON.stringify({type: "testJoystick", data: {axes: [steer_deg, accel_brake], buttons: buttons}})
    dc.send(message);
  }
  function checkLatency() {
    const initialTime = new Date().getTime();
    pingHeadRequest().then(function() {
      const currentTime = new Date().getTime();
      if (Math.abs(currentTime - lastChannelMessageTime) < 1000) {
        const pingtime = currentTime - initialTime;
        pingPoints.push({'x': currentTime, 'y': pingtime});
        if (pingPoints.length > 1000) {
          pingPoints.shift();
        }
        chartPing.update();
        $("#ping-time").text((pingtime) + "ms");
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
    controlCommandInterval = setInterval(sendJoystickOverDataChannel, 50);
    latencyInterval = setInterval(checkLatency, 1000);
    sendJoystickOverDataChannel();
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

            if (msg.data.cruiseState.available) {
                if (msg.data.cruiseState.enabled) {
                    $("#cruise").text('CC:ON');
                    setCruiseEnabledActive(true);
                } else {
                    $("#cruise").text("CC:OFF");
                    setCruiseEnabledActive(false);
                }
            } else {
                $("#cruise").text("CC:NAN");
                setCruiseEnabledActive(false);
            }
        }
        setSteerCurrent(msg.data.steeringAngleDeg);
    }

    carStaterIndex += 1;
    lastChannelMessageTime = new Date().getTime();
    $(".pre-blob").addClass('blob');
  };


  negotiate(pc)
    .catch(function (err) {
      console.error('negotiate error:', err);
      alert('Negotiation failed: ' + err);
    });

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
}
