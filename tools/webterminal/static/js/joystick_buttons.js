
import { SliderController } from './slider_controller.js';
import { SteeringWheelJoystick } from './steer_wheel.js';
import { executePlan } from "./controls.js";

let isJoystickActive = false;
let isJoystickCruise = false;
const plotterBut = document.getElementById('plotter-btn');
const parametersPanel = document.getElementById('plotter-modal');

const MAX_STEER_ANGLE = 580; // Максимальный угол поворота руля в градусах

const sliderController = new SliderController();

const IS_DEBUG_MODE = false;

function togglePlotterModal() {

    if (parametersPanel.classList.contains('visible')) {
        parametersPanel.classList.remove('visible');
        plotterBut.classList.remove('active');
    } else {
        parametersPanel.classList.add('visible');
        plotterBut.classList.add('active');
        executePlan();
    }
}




function enableJoystick() {
    isJoystickActive = true;
    joystickActiveBtn.classList.remove('active');
    joystickActiveBtn.classList.add('active');
    //sendJoystickCommand({joystick: {joystick_control_active: true}});
    console.debug('Sending joystick enabled');
    steeringWheelJoystick.setJoystickActive(isJoystickActive);
}

function disableJoystick() {
    isJoystickActive = false;
    joystickActiveBtn.classList.remove('active');
    //sendJoystickCommand({joystick: {joystick_control_active: true}});
    console.debug('Sending joystick disabled');

    steeringWheelJoystick.setJoystickActive(isJoystickActive);
}


function toggleJoystickEnableState() {

    if (joystickActiveBtn.classList.contains('active')) {
        disableJoystick();
    } else {
        enableJoystick();
    }

    steeringWheelJoystick.setJoystickActive(isJoystickActive);

}


function toggleJoystickCruiseActiveBtnState() {
    joystickCruiseActiveBtn.classList.remove('active');
    if (isJoystickCruise) {
        isJoystickCruise = false;
    } else {
        joystickCruiseActiveBtn.classList.add('active');
        isJoystickCruise = true;
    }
}

// ========= Steering Wheel Joystick ==========
let steeringWheelJoystick = null;
function  initSteeringWheelJoystick(maxRotationAngle=710) {
    if (steeringWheelJoystick !== null) {
        steeringWheelJoystick.destroy();
        steeringWheelJoystick = null;
    }

    steeringWheelJoystick = new SteeringWheelJoystick(
        'steer-wheel-joystick-container', {
            steerSetCallback: setSteerTurnValue,
            sliderControllerClass : sliderController,
            isVisibleOnStart : true,
            isInfoFrameActive : true,
            infoFramePosition : '',
            isUsingDragHandle : true,
            stepBackActive : false,
            maxRotationAngle: maxRotationAngle,
            counterClockwiseMode: true,

            debudMode: IS_DEBUG_MODE,
        }
    );
    steeringWheelJoystick.setJoystickEnable(true);
    steeringWheelJoystick.setJoystickActive(false);
    enableJoystick();
    disableJoystick();
}



function handleRealSteerValue(angle){
    if (steeringWheelJoystick !== null) {
        steeringWheelJoystick.setHardwareSteerAngle(angle);
    }
}

//=== joystick control buttons ===
const joystickActiveBtn = document.getElementById('joystick-active-btn');
const joystickCruiseActiveBtn = document.getElementById('joystick-cruise-active-btn');
const throttleValue = document.getElementById('joystick-value-throttle');
const stopBtn = document.getElementById('stop-btn');
const stopBtnFrame = document.getElementById('throttle-stop-frame');


// Общий объект для управления состоянием команд
const joystickState = {
    steer_turn: 0.0,// угол поворота руля
    parking_brake: false, // тормоз
    throttleBrake: 0.0, // газ

    move_backward: false, // Номинальный режим

};

function setSteerTurnValue(value) {
    joystickState.steer_turn = value;
}

export function setSteerMaxRotationAngle(value) {
    if (steeringWheelJoystick !== null) {
        steeringWheelJoystick.setMaxRotationAngle(value);
    }
}

export function setSteerCurrent(value) {
    if (steeringWheelJoystick !== null) {
        steeringWheelJoystick.setHardwareSteerAngle(value);
    }
}


function updateThrottleBrakeInfo() {
    // отображение значение в названии turnToZeroBtn
    if (joystickState.throttleBrake < 0) {
        throttleValue.innerHTML = `↓${joystickState.throttleBrake.toFixed(0) }%`;
    }else if (joystickState.throttleBrake > 0) {
        throttleValue.innerHTML = `↑${joystickState.throttleBrake.toFixed(0) }%`;
    }else {
        //throttleValue.innerHTML = '⇅';
        throttleValue.innerHTML = '→|←';
    }
}

function addTurnValue(value, valueName) {
    joystickState[valueName] += value;
    if (joystickState[valueName] > 100.0) {
        joystickState[valueName] = 100.0;
    }else if (joystickState[valueName] < 0.0) {
        joystickState[valueName] = 0.0;
    }
    updateThrottleBrakeInfo();
}

// Слушатели событий



function setThrottleBrakeValue(value) {
    if (joystickState.parking_brake){
        joystickState.throttleBrake = -50.0;
    } else{
        joystickState.throttleBrake = value;
        if (joystickState.throttleBrake > 100.0) {
            joystickState.throttleBrake = 100.0;
        }else if (joystickState.throttleBrake < -100.0) {
            joystickState.throttleBrake = -100.0;
        }
    }

    updateThrottleBrakeInfo();
}

function throttleBrakeAdd(value) {
    if (joystickState.parking_brake){
        joystickState.throttleBrake = -50.0;
    } else{
        joystickState.throttleBrake += value;
        if (joystickState.throttleBrake > 100.0) {
            joystickState.throttleBrake = 100.0;
        }else if (joystickState.throttleBrake < -100.0) {
            joystickState.throttleBrake = -100.0;
        }
    }

    updateThrottleBrakeInfo();
}


let throttleBrakeSliderStepToValFunc = null;

function registerThrottleBrakeBut() {

    let isThrottleBrakeActive = false;
    let throttleBrakeInterval = null;
    const clearIntervalFunc = () => {
        if (throttleBrakeInterval !== null) {
            clearInterval(throttleBrakeInterval);
            throttleBrakeInterval = null;
        }
    }

    throttleBrakeSliderStepToValFunc = (targetValue, immediately=false) => {
        clearIntervalFunc();

        if (joystickState.throttleBrake !== targetValue) {
            if (isThrottleBrakeActive) {  return; }
            if (immediately){
                setThrottleBrakeValue(targetValue);
                const newThrottleBrakeValue = (targetValue + 100) / 2;
                sliderController.moveSliderPercent('slider-accel-brake', newThrottleBrakeValue);
                return;
            }

            throttleBrakeInterval = setInterval(() => {
                if (isThrottleBrakeActive) {
                    clearIntervalFunc();
                    return;
                }

                let throttleBrakeSliderVal = joystickState.throttleBrake;
                if (throttleBrakeSliderVal > targetValue) {
                    throttleBrakeSliderVal -= 3;
                    if (throttleBrakeSliderVal <= targetValue) {
                        throttleBrakeSliderVal = 0;
                        clearIntervalFunc(); //Complete
                    }
                } else if (throttleBrakeSliderVal < targetValue) {
                    throttleBrakeSliderVal += 3;
                    if (throttleBrakeSliderVal >= targetValue) {
                        throttleBrakeSliderVal = 0;
                        clearIntervalFunc(); //Complete
                    }
                } else {
                    clearIntervalFunc(); //Complete
                }

                const newThrottleBrakeValue = (throttleBrakeSliderVal + 100) / 2;
                sliderController.moveSliderPercent('slider-accel-brake', newThrottleBrakeValue);

            }, 70);
        }
    }


    sliderController.registerSlider('slider-accel-brake', 'slider-accel-brake-knob', {
        isVerticalSlider : true,
        onPressed: (joystickCircle, joystickKnob, clientXY) => {

            if (isJoystickActive && !joystickState.parking_brake) {
                console.log(`slider-accel-brake нажато: Active`);
                isThrottleBrakeActive = true;
                clearIntervalFunc();
                return true;
            }else {
                return false;
            }
        },

        onProgress: (slider, knob, newLeftPercent) => {
            if (!isJoystickActive) return;
            const throttleBrakeSliderVal = newLeftPercent*2 - 100;
            setThrottleBrakeValue(throttleBrakeSliderVal);
            console.log('Throttle:', throttleBrakeSliderVal, '%');
        },
        onDragEnd: (joystickCircle, joystickKnob) => {
            console.log('slider-accel-brake завершено');
            isThrottleBrakeActive = false;
            throttleBrakeSliderStepToValFunc(0.0);
        },
        isStopPropagation: true,
        initialPositionPercent: 50
    });

    setThrottleBrakeValue(0);
    throttleBrakeSliderStepToValFunc(0, true);
}


// Обработчик для кнопок "Стоп" (Блокируемые)
function toggleBlockableStopButton() {

    if (joystickState.parking_brake ) {
        stopBtn.classList.remove('pressed');
        stopBtnFrame.classList.remove('active');
        console.debug('Stop button released');
        joystickState.parking_brake = false;
        if (throttleBrakeSliderStepToValFunc !== null) {
            throttleBrakeSliderStepToValFunc(0.0, true);
        }else {
            setThrottleBrakeValue(0.0);
        }
    }else {
        console.debug('Stop button pressed');
        joystickState.parking_brake = true;
        stopBtn.classList.add('pressed');
        stopBtnFrame.classList.add('active');
        if (throttleBrakeSliderStepToValFunc !== null) {
            throttleBrakeSliderStepToValFunc(-50.0, true);
        }else {
            setThrottleBrakeValue(-50.0);
        }
    }

    publishJoystickCommand();
}

function handleJoystickFeedback(joystickFeedback) {

    if ('steer_turn' in joystickFeedback) {
        handleRealSteerValue(joystickFeedback.steer_turn);
    }

    if ('parking_brake' in joystickFeedback) {
        if (joystickFeedback.parking_brake !== joystickState.parking_brake) {
            toggleBlockableStopButton();
            console.log('Parking brake:', joystickFeedback.parking_brake);
        }
    }

    if ('throttle' in joystickFeedback) {

    }

    if ('brake' in joystickFeedback) {

    }

}


function getSteerFactor() {
    let factor = 0.0;
    if (steeringWheelJoystick !== null && isJoystickActive) {
        let  percent = steeringWheelJoystick.getSteerPercent();
        factor = percent / 100.0;
    }
    return factor;
}

function getSteerPercent() {
    let percent = 0.0;
    if (steeringWheelJoystick !== null && isJoystickActive) {
        percent = steeringWheelJoystick.getSteerPercent();
    }
    return percent;
}

function getSteerAngle() {
    let ang = 0.0;
    if (steeringWheelJoystick !== null && isJoystickActive) {
        ang = steeringWheelJoystick.getSteerAngle();
        if (ang === null){
            ang = 0.0;
        }
    }
    return ang;
}

function getAccelBrakeFactor() {
    let factor = 0.0;
    if (isJoystickActive) {
        factor = (joystickState.throttleBrake) / 100.0;
    }
    return factor;
}




function steerManualAdd(value) {
    if (steeringWheelJoystick !== null) {
        steeringWheelJoystick.manualSteerAdd(value);
    }
}

function manualActiveSteer(value) {
    if (steeringWheelJoystick !== null) {
        steeringWheelJoystick.manualActiveSteer(value);
    }
}


// ====== Keyboard control W/S/A/D ======

function onKepPressSetKeyboardWS(side) {
    if (joystickState.parking_brake || !isJoystickActive) {
        joystickState.throttleBrake = 0;
        return;
    }
    if (side === 's') {
        throttleBrakeAdd(-3.0);
    } else if (side === 'w') {
        throttleBrakeAdd(2.0);
    }
}

function onKepPressSetKeyboardAD(side) {
    if (!isJoystickActive){
        manualActiveSteer(false);
        return;
    }
    if (side === 'right') {
         manualActiveSteer(true);
        steerManualAdd(5);
        // keyboardAD_timer = setInterval(() => {
        //     steerManualAdd(5);
        // }, 100);
    }else if (side === 'left') {
         manualActiveSteer(true);
        steerManualAdd(-5);
        // keyboardAD_timer = setInterval(() => {
        //     steerManualAdd(-5);
        // }, 100);
    } else {
        manualActiveSteer(false);
    }
}

const pressed = new Set();
function keyboardInit(){
    // Клавиатура: W/S/A/D/R

    function updateButtons() {
      if (pressed.has('KeyW')) { onKepPressSetKeyboardWS('w'); }
      else if (pressed.has('KeyS')) { onKepPressSetKeyboardWS('s'); }
      else {
          onKepPressSetKeyboardWS('');
      }

      if (pressed.has('KeyA')) { onKepPressSetKeyboardAD('left'); }
      else if (pressed.has('KeyD')) { onKepPressSetKeyboardAD('right'); }
        else {
            onKepPressSetKeyboardAD('');
        }

      if (pressed.has('Space')) {
          // Reset steering wheel position
          toggleBlockableStopButton();
      }
      if (pressed.has('ShiftLeft') || pressed.has('ShiftRight')) {
          // Reset steering wheel position
          toggleJoystickEnableState();
      }

      // для отладки
      console.log("Pressed:", Array.from(pressed));
    }
    document.addEventListener('keydown', (e) => {
      pressed.add(e.code);
      updateButtons();
    });

    document.addEventListener('keyup', (e) => {
      pressed.delete(e.code);
      //updateButtons();
    });

}


// Пример инициализации
document.addEventListener('DOMContentLoaded', () => {

    //joystickButtonsRegistration
    plotterBut.addEventListener('click', () => togglePlotterModal());
    joystickActiveBtn.addEventListener('click', () => toggleJoystickEnableState());
    joystickCruiseActiveBtn.addEventListener('click', () => toggleJoystickCruiseActiveBtnState());
    stopBtn.addEventListener('click', () => toggleBlockableStopButton());
    registerThrottleBrakeBut();

    initSteeringWheelJoystick(MAX_STEER_ANGLE);

    keyboardInit();
});


export function getJoystickXY() {
  //let x = getSteerPercent();
  const steer_deg = getSteerAngle();
  const accel_brake = getAccelBrakeFactor();
  return {steer_deg, accel_brake, isJoystickActive ,isJoystickCruise}
}

export function onWindowResizeNext() {

    const joystickRight = document.getElementById('joystick-container-right');
    const joystickSpace = document.getElementById('joystick-button-space');
    joystickRight.classList.add('visible');
    joystickSpace.classList.add('visible');
    steeringWheelJoystick.resizeHandler();
}


export function getIsJoystickActive(){
    return isJoystickActive;
}

export function setCruiseEnabledActive(isEnabled){
    if(isJoystickCruise !== isEnabled){
        toggleJoystickCruiseActiveBtnState();
    }
}

