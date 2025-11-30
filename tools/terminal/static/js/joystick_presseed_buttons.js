
function registerJoystickPressedBut(buttonId, valueName, stepOnStart, stepOnHold, addTurnCb) {

    if (typeof addTurnCb !== 'function') {
        console.error('addTurnValueCb is not a function');
        return;
    }
    // throttle
    sliderController.registerSlider(buttonId, buttonId, {
        minPosition: 0,
        maxPosition: 0,
        activateDelay: 0, //  мс для включения
        deactivateDelay: 0, //  мс для выключения
        onPressed: (slider, knob, clientXY) => {
            slider.classList.remove('released');
            slider.classList.add('pressed');
            addTurnCb(stepOnStart);
            return true;
        },
        periodicTaskOnPressed: (slider, knob, duration, clientXY) => {
            console.log(`${slider.id} periodicTask`);
            if (isJoystickActive) {
                if (duration > 1500) {
                    addTurnCb(stepOnHold * 4, valueName);
                } else if (duration > 900) {
                    addTurnCb(stepOnHold * 3, valueName);
                } else if (duration > 400) {
                    addTurnCb(stepOnHold * 2, valueName);
                } else if (duration > 200) {
                    addTurnCb(stepOnHold, valueName);
                }
            }
        },
        onDragEnd: (slider, knob) => {
            console.debug(`${slider.id} завершено`);
            slider.classList.remove('pressed');
            slider.classList.add('released');
        }
    });

}


function setActiveJoystickTurnButtons(state){
    const joystickButBox = document.getElementById('joystick-diagonal-buttons-container');
    if (state){
        joystickButBox.classList.add('active');
    }else {
        joystickButBox.classList.remove('active');
    }
}
function joystickPressedButtonsRegistration() {

// registerJoystickPressedBut('throttle-btn-minus','throttle', -1.0, -2.0);
// registerJoystickPressedBut('throttle-btn-plus', 'throttle',1.0, 2.0);
// registerJoystickPressedBut('brake-btn-minus', 'brake',-1.0, -2.0);
// registerJoystickPressedBut('brake-btn-plus', 'brake',1.0, 2.0);
}
