
class SteeringWheelJoystick {

    constructor(containerId,  options = {}) {
        this.steerContainer = document.getElementById(containerId);

        if (!this.steerContainer) {
            throw new Error(`steerContainer with ID "${containerId}" not found.`);
        }
        const rect = this.steerContainer.getBoundingClientRect();
        this.isLeftPosition = rect.left < window.innerWidth / 2;

        this.isJoystickActive = false;
        this.lastRotationCCW = -1000;

        this.isTurning = false;
        this.isFirstInit = false;
        this.centerX = 0;
        this.centerY = 0;
        this.circleTransEnd = false;

        this.radius = 0; // Radius of the circle
        this.totalRotationCCW = 0; // Total RotationCCW
        this.realTotalRotationCCW = 0; // Real total RotationCCW
        this.realHardwareRotationCCW = 0; // Real hardware RotationCCW
        this.lastAngle = 0; // Last angle for calculation
        this.turnHandlerTimer = null;
        this.publishLastTime = 0;
        this.lastFiilState = 0;



        this.dragFrameData = {
            isDragging: false,
            startX: 0,
            startY: 0,
            lastClientX: 0,
            lastClientY: 0,
            maxTop: 0,
            maxBottom: 0,
            maxLeft: 0,
            maxRight: 0,
            currIdentifier: null,
        };

        this.counterClockwiseMode = this.getValueOption(options.counterClockwiseMode, true); // Right turn sign
        this.publishInterval = this.getValueOption(options.publishInterval, 100); // ms for publishing
        this.isUsingColorCircles = this.getBoolOption(options.isUsingColorCircles ,true); // Using color circles
        this.isUsingDragHandle = this.getBoolOption(options.isUsingDragHandle ,true); // Using drag handle

        this.isVisibleOnStart = this.getBoolOption(options.isVisibleOnStart ,false);

        this.stepBackDegreePerSec = this.getValueOption(options.stepBackDegreePerSec, 100);  // grad/sec for auto turn back: 0 - is off
        this.stepBackPeriodMs = this.stepBackDegreePerSec > 0  ? 1000/(this.stepBackDegreePerSec/2)  : 20;
        this.stepBackActive = this.getBoolOption(options.stepBackActive ,true);

        const stepDegreePerSec = this.getValueOption(options.stepDegreePerSec, 280); // grad/sec for turning
        this.stepDegreePerSec = stepDegreePerSec > 100 ? 1000/stepDegreePerSec : 10;

        this._steerSetCallback = options.steerSetCallback || null; // Callback for setting steering angle ( negative for clockwise).
        this.sliderControllerClass = options.sliderControllerClass || null; // Class for slider controller
        this.maxRotationAngle = this.getValueOption(options.maxRotationAngle, 500); // Max rotation angle
        this.onCenterPressed  = options.onCenterPressed || this.toggleStepBackActive; // Callback for center pressed: default is switch on/off stepBackActive
        this.infoFramePosition = options.infoFramePosition || 'top'; // Position of the information frame [top, bottom, left, right, center]
        this.isInfoFrameActive = this.infoFramePosition !== ''; // To show or hide the information frame

        this.debudMode = this.getBoolOption(options.debudMode ,false); // Debug mode

        this.initJoystick();
        console.log('Joystick created successfully.');
        if (this.isVisibleOnStart){
            this.steerMainCircle.classList.add('visible');
            this.placeSteerJoyOnInit();
            this.steerMainCircle.classList.add('active');
            this._onFirstInit();
            this.isFirstInit = true;
        }
    }

    resizeHandler(){
        if (this.steerMainCircle.classList.contains('visible')) {
            this.placeSteerJoyOnInit();
            this.steerMainCircle.classList.add('active');
            this._onFirstInit();
            this.isFirstInit = true;
            console.log('Joystick resized and repositioned.');
        }
    }

    getBoolOption(option, defState){
        return option === null || option === undefined ? defState:  option;
    }
    getValueOption(option, defVal){
        return option === null || option === undefined ? defVal:  option;
    }
    initJoystick() {

        this.joystickContainerName = 'steer-wheel-joystick-container';
        this.containerDragName = 'steer-drag-handle';
        this.steerMainCircleName = 'steer-circle';
        this.steerKnobName = 'steer-knob';
        this.steerCircleImageName = 'steer-circle-image';
        this.steerInnerCircleName = 'steer-inner-circle';
        this.steerOuterCircleName = 'steer-outer-circle';
        this.steerCenterCircleName = 'steer-center-circle';
        this.steerNonHandleAreaName = 'steer-non-handle-area';
        this.steerInfoName = 'steer-info';


        // Create joystick elements
        this.joystickContainer = document.createElement('div');
        this.joystickContainer.classList.add('joystick-container', 'left');
        this.joystickContainer.id = this.joystickContainerName;

        this.steerMainCircle = document.createElement('div');
        this.steerMainCircle.classList.add('steer-circle');
        this.steerMainCircle.id = this.steerMainCircleName;

        this.steerNonHandleArea = document.createElement('div');
        this.steerNonHandleArea.classList.add('steer-non-handle-area');
        this.steerNonHandleArea.id = this.steerNonHandleAreaName;

        this.steerCircleImage = document.createElement('div');
        this.steerCircleImage.classList.add(this.steerCircleImageName);
        this.steerCircleImage.id = this.steerCircleImageName;

        this.lines = ['top', 'right', 'bottom', 'left'].map(position => {
            let line = document.createElement('div');
            line.classList.add('steer-line', position);
            return line;
        });

        this.steerInnerCircle = document.createElement('div');
        this.steerInnerCircle.classList.add('steer-second-circle', 'inner');
        this.steerInnerCircle.id = this.steerInnerCircleName;

        this.steerCenterCircle = document.createElement('div');
        this.steerCenterCircle.classList.add(this.steerCenterCircleName);
        this.steerCenterCircle.id = this.steerCenterCircleName;

        let isHardwareCircle = true;

        if (isHardwareCircle) {
            this.steerHarwareCircle = document.createElement('div');
            this.steerHarwareCircle.classList.add(this.steerCenterCircleName);
            this.steerHarwareCircle.classList.add('hardware');
            this.steerHarwareCircle.id = this.steerCenterCircleName+'-hardware';

            this.steerHarwarePoint = document.createElement('div');
            this.steerHarwarePoint.classList.add('steer-hardware-point');
            this.steerHarwarePoint.id = this.steerCenterCircleName+'-point';

            this.steerHarwareCircle.appendChild(this.steerHarwarePoint);

        } else {
            this.steerHarwareCircle = null;
        }

        this.steerOuterCircle = document.createElement('div');
        this.steerOuterCircle.classList.add('steer-second-circle', 'outer');
        this.steerOuterCircle.id = this.steerOuterCircleName;


        this.steerInfo = document.createElement('div');
        this.steerInfo.classList.add(this.steerInfoName);
        this.steerInfo.id = this.steerInfoName;
        this.steerInfo.textContent = '---';

        //Info block options
        if (this.infoFramePosition.includes('center') ){
            if (this.infoFramePosition.includes('top')) {
                this.steerInfo.classList.add('top-center');
            }else if (this.infoFramePosition.includes('bottom')) {
                this.steerInfo.classList.add('bottom-center');
            }else {
                this.steerInfo.classList.add(this.isLeftPosition ? 'right-center' :'left-center');
            }
        } else {
            if (this.infoFramePosition.includes('left')) {
                this.steerInfo.classList.add('left');
            }else if (this.infoFramePosition.includes('right')) {
                this.steerInfo.classList.add('right');
            }else {
                this.steerInfo.classList.add(this.isLeftPosition ? 'left' :'right');
            }
            if (this.infoFramePosition.includes('bottom')) {
                this.steerInfo.classList.add('bottom');
            } else {
                this.steerInfo.classList.add('top');
            }
        }

        this.steerInfo.style.display = this.isInfoFrameActive ? 'block' : 'none';
        this.steerInfo.innerText = 'init';

        this.knobWrap = document.createElement('div');
        this.knobWrap.classList.add('steer-center-circle');
        this.knobWrap.classList.add('knob');
        this.knobWrap.id = this.steerKnobName;
        this.knobPoint = document.createElement('div');
        this.knobPoint.classList.add('steer-knob-inner');
        this.knobPoint.id = this.steerKnobName+'-point';
        this.knobWrap.appendChild(this.knobPoint);

        this.steerMainCircle.appendChild(this.steerNonHandleArea);
        this.steerMainCircle.appendChild(this.steerCircleImage);
        this.lines.forEach(line => this.steerMainCircle.appendChild(line));
        this.steerMainCircle.appendChild(this.steerInnerCircle);
        this.steerMainCircle.appendChild(this.steerCenterCircle);
        if (isHardwareCircle) {
            this.steerMainCircle.appendChild(this.steerHarwareCircle);
        }
        this.steerMainCircle.appendChild(this.steerOuterCircle);
        this.steerMainCircle.appendChild(this.steerInfo);
        this.steerMainCircle.appendChild(this.knobWrap);
        if (this.isUsingDragHandle){
            this.steerDragHandle = document.createElement('div');
            this.steerDragHandle.classList.add(this.containerDragName);
            this.steerDragHandle.id = this.containerDragName;
            this.steerDragHandle.textContent = '⬍';
            if (this.isLeftPosition) {
                this.steerDragHandle.classList.add('left');
            } else {
                this.steerDragHandle.classList.add('right');
            }
            this.steerMainCircle.appendChild(this.steerDragHandle);
        }
        this.joystickContainer.appendChild(this.steerMainCircle);

        // Add joystick to the container
        this.steerContainer.appendChild(this.joystickContainer);
        this._registerEvents( this.sliderControllerClass); // Регистрация событий

        this.currIdentifier = null;

        this._setCircleFillToZero(); // initial setting of the circles

    }

    _printLog(msg){
        if (this.debudMode) {
            console.log(msg);
        }
    }

    _registerEvents(sliderControllerClass) {
        this.steerMainCircle.addEventListener('transitionend', (event) => {
            if (event.propertyName === 'width') {
                this.circleTransEnd = true;
            }
        });


        if (sliderControllerClass && sliderControllerClass instanceof Object) {

            sliderControllerClass.registerSlider(this.joystickContainerName, this.joystickContainerName, {
                onPressed: (slider, knob, clientXY) => {
                    return this._onStart(clientXY.x, clientXY.y);
                },
                funcHandleOnMove: (joystickCircle, joystickKnob, options, clientXY) => {
                    this._onMove(clientXY.x, clientXY.y);
                },
                onDragEnd: (slider, knob) => {
                    this._onEnd();
                }
            });

            if (this.isUsingDragHandle) {
                sliderControllerClass.registerSlider(this.containerDragName, this.containerDragName, {
                    onPressed: (slider, knob, clientXY) => {
                        return this._onDragStart(clientXY.x, clientXY.y);
                    },
                    funcHandleOnMove: (joystickCircle, joystickKnob, options, clientXY) => {
                        this._onDrag(clientXY.x, clientXY.y);
                    },
                    onDragEnd: (slider, knob) => {
                        this._onDragEnd();
                    }
                });
            }
            this._printLog('Joystick registered with exist sliderController.');

        } else {

            this.joystickContainer.addEventListener('touchstart', (e) => this._onStartGlobal(e));
            this.joystickContainer.addEventListener('mousedown', (e) => this._onStartGlobal(e));


            if (!('ontouchstart' in window)) {
                this.joystickContainer.addEventListener('mousemove', (e) => this._obMoveGlobal(e), {passive: false});
                if (this.isUsingDragHandle) {
                    this.steerDragHandle.addEventListener('mousemove', (e) => this._onDragGlobal(e), {passive: false});
                }
                document.addEventListener('touchmove', (e) => this._obMoveGlobal(e), {passive: false});
                document.addEventListener('mouseup', (e) => this._onEndGlobal(e), {passive: false});
            }
            document.addEventListener('touchend', (e) => this._onEndGlobal(e));
            document.addEventListener('touchcancel', (e) => this._onEndGlobal(e));

            if (this.isUsingDragHandle) {
                // Перемещение круга с помощью кнопки
                this.steerDragHandle.addEventListener('mousedown', (e) => this._onDragStartGlobal(e));
                this.steerDragHandle.addEventListener('touchstart', (e) => this._onDragStartGlobal(e));
                this.steerDragHandle.addEventListener('touchmove', (e) => this._onDragGlobal(e));
            }

            this._printLog('Joystick registered with internal event handlers.');
        }
    }

    //==== main functions ====

    /**
     * Function for handling the start of the touch event by internal event handler
     * @param event
     */
    _onStartGlobal(event){
        this.currIdentifier =  this._getTouchIdentifier(event);
        if (!this.currIdentifier) {
            return;
        }
        const clientXY =event.touches ? event.touches[0] : event;
        this._onStart(clientXY.clientX, clientXY.clientY);
    }

    _onStart(x, y){

        if (!this.steerMainCircle.classList.contains('visible')) {
            this._firstPlacing(x, y);
            this._printLog('On Start: first placing done.');
            return false;  // First touch is skipped for handle -only visual effect
        }

        if (!this.isJoystickActive || this.dragFrameData.isDragging) return false;

        if (this.steerMainCircle.classList.contains('active')) {
            // Synchronize with drag handle
            if (this.isFirstInit) {
                if (!this._onSecondInitCheckCenter(x, y)){
                    this._printLog('On Start: second init check center failed.');
                    return false;
                }
            }
        }else{
            this.steerMainCircle.classList.add('active');
            if (this.circleTransEnd) {
                this._printLog('On Start: first init done.');
                this._onFirstInit();
                this.isFirstInit = true;
            }
        }
        this.isTurning = true;
        this._startTurnHandler();
        this._printLog('On Start: turn started.');
        return true;
    };

    /**
     * Function for handling the drag event by internal event handler
     * @param event
     */
    _obMoveGlobal(event){
        const clientXY = this.getTargetTouch(event, this.currIdentifier);
        if (!clientXY) {
            return;
        }
        this._onMove(clientXY.clientX, clientXY.clientY);
    }

    _onMove(clientX, clientY) {

        if (!this.isJoystickActive) return;

        if (!this.isTurning || this.dragFrameData.isDragging) {
            return;
        }

        if (!this.isFirstInit) {
            if (this.circleTransEnd) {
                this._onFirstInit();
                this.isFirstInit = true;
                return this._onSecondInitCheckCenter(clientX, clientY);
            } else {
                return;
            }
        }

        const dx = clientX - this.centerX;
        const dy = clientY - this.centerY;
        const currentAngle = this._getCurrAngle(dx, dy);

        // Вычисляем изменение угла
        let deltaAngle = currentAngle - this.lastAngle;  // 5 - 355 = -350
        this.lastAngle = currentAngle;

        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < this.radius * 0.4 || distance > this.radius * 1.5) {
            this.steerNonHandleArea.classList.add('active');
            return;
        } else {
            this.steerNonHandleArea.classList.remove('active');
        }

        // Check for zero crossing
        if (deltaAngle > 180) deltaAngle = deltaAngle - 360;
        if (deltaAngle < -180) deltaAngle = 360 + deltaAngle;

        // update total RotationCCW
        let dReal;
        if (this.totalRotationCCW < this.realTotalRotationCCW) {
            dReal = this.realTotalRotationCCW - this.totalRotationCCW;
        } else {
            dReal = this.totalRotationCCW - this.realTotalRotationCCW;
        }
        if (dReal < 45) {
            this.totalRotationCCW += deltaAngle;
            this.totalRotationCCW = Math.max(-this.maxRotationAngle, Math.min(this.maxRotationAngle, this.totalRotationCCW));
        }

         this._printLog('On Move: totalRotationCCW='+this.totalRotationCCW);
    }

    /**
     * Function for handling the start of the touch event by internal event handler
     * @param event
     */
    _onDragStartGlobal(event){
        this.dragFrameData.currIdentifier = this._getTouchIdentifier(event);
        if (!this.dragFrameData.currIdentifier) {
            return;
        }
        const clientXY =event.touches ? event.touches[0] : event;
        if (!this._onDragStart(clientXY.clientX, clientXY.clientY)){
            this.dragFrameData.currIdentifier = null;
        }
    }
    _onDragStart(clientX, clientY){
        if ((!this.isJoystickActive && !this.isVisibleOnStart) || this.isTurning){
            this._printLog('On Drag Start: drag start skipped: isVisibleOnStart = '+this.isVisibleOnStart+', isTurning='+this.isTurning+ '.');
            return false;
        }

        this.dragFrameData.isDragging = true;
        this.dragFrameData.startX = clientX  - this.steerMainCircle.offsetLeft;
        this.dragFrameData.startY = clientY  - this.steerMainCircle.offsetTop;
        this.dragFrameData.lastClientX = clientX;
        this.dragFrameData.lastClientY = clientY;

        const rect = this.joystickContainer.getBoundingClientRect();
        const rectCirc = this.steerMainCircle.getBoundingClientRect();

        this.dragFrameData.maxTop = rect.top;
        this.dragFrameData.maxLeft = rect.left  + rectCirc.width*0.05;
        this.dragFrameData.maxBottom = rect.bottom ;
        this.dragFrameData.maxRight = rect.right ;

        return true;
    }

    _firstPlacing(x, y, circleWidthVal = null ){
        //if (!this.steerMainCircle.classList.contains('visible')) {
            this.centerX = x;
            this.centerY = y;
            this._setCircleInitialPos(circleWidthVal);
            this.steerMainCircle.classList.add('visible');
            this._startAutoTurnBack();
       // }
    }
    /**
     * Function for handling the drag event by internal event handler
     * @param event
     */
    _onDragGlobal(event){
        const clientXY = this.getTargetTouch(event, this.dragFrameData.currIdentifier);
        if (clientXY) {
            this._onDrag(clientXY.clientX, clientXY.clientY);
        }

    }
    _onDrag(clientX, clientY){
        if ((!this.isJoystickActive && !this.isVisibleOnStart) || !this.dragFrameData.isDragging){
            this._printLog('On Drag: drag move skipped.');
            return;
        }

        this._printLog('On Drag: drag move processed.');
        let deltaX = clientX - this.dragFrameData.startX;
        let deltaY = clientY - this.dragFrameData.startY;

        //Check for limits of the joystick
        const rectCirc = this.steerMainCircle.getBoundingClientRect();

        let isXToLeft = this.dragFrameData.lastClientX > clientX;
        let isYToTop = this.dragFrameData.lastClientY > clientY;

        if (deltaX > 0 ){
            if ((rectCirc.right < this.dragFrameData.maxRight || isXToLeft) &&
                (rectCirc.left > this.dragFrameData.maxLeft || !isXToLeft)) {
                this.steerMainCircle.style.left = `${deltaX}px`;
            }
        }

        if (deltaY > 0 ){
            if ((rectCirc.top > this.dragFrameData.maxTop || !isYToTop) &&
                (rectCirc.bottom < this.dragFrameData.maxBottom || isYToTop)) {
                this.steerMainCircle.style.top = `${deltaY}px`;
            }
        }

        this.dragFrameData.lastClientX = clientX;
        this.dragFrameData.lastClientY = clientY;

        this.centerX = rectCirc.left + rectCirc.width / 2;
        this.centerY = rectCirc.top + rectCirc.height / 2;

    }
    _onDragEnd() {
        this.dragFrameData.isDragging = false;
        this._printLog('On Drag End: drag end processed.');
    }

    _onEnd (){
        if (this.isTurning) {
            this.isTurning = false;
            this.steerNonHandleArea.classList.remove('active');

        }
        this._printLog('On End: turn stopped.');
        this._startAutoTurnBack();
        this.dragFrameData.isDragging = false;
    }

    /**
     * Function for handling the end of the touch event by internal event handler
     * @param event
     */
    _onEndGlobal(event){
        if (event.changedTouches){
            for (const touch of event.changedTouches) {
                if (touch.identifier === this.dragFrameData.currIdentifier) {
                    this._onDragEnd();
                    this.dragFrameData.currIdentifier = null;
                    // event.preventDefault();
                    this._printLog('On End Global: drag end processed.');
                }else if (touch.identifier === this.currIdentifier) {
                    this._onEnd();
                    this.currIdentifier = null;
                    // event.preventDefault();
                    this._printLog('On End Global: touch end processed.');
                }
            }
        }else {
            if (this.dragFrameData.currIdentifier !== null) {
                 this._printLog('On End Global: drag end processed.');
                this._onDragEnd();
                this.dragFrameData.currIdentifier = null;
                // event.preventDefault();
            }
            if (this.currIdentifier !== null) {
                this._printLog('On End Global: mouse end processed.');
                this._onEnd();
                this.currIdentifier = null;
                // event.preventDefault();
            }
        }
    }

    //====== additional functions ======
    /**
     * Function for setting the new steering angle. It is internal function.
     * Used for send to callback for the steering value.
     * @param steerAngle - angle of the steering wheel ( negative for clockwise, positive for counterClockwiseMode)
     */
    _setNewSteer(steerAngle){
        if (Date.now() - this.publishLastTime < this.publishInterval) {
            return;
        }
        this._setNewSteerNoWait(steerAngle);
    }
    _setNewSteerNoWait(steerAngle){
        if (this.isTurning && steerAngle === 0) {
            // when steering and holding at 0, to use external control it needs to maintain a non-zero value.
            this._sendSteerValToCb(0.01);  //
        } else {
            this._sendSteerValToCb(steerAngle);
        }
        this.publishLastTime = Date.now();
    }
    _sendSteerValToCb(val){
        if (this._steerSetCallback) {
            this._steerSetCallback(val * (this.counterClockwiseMode ? 1 : -1));
        }
    }
    _stopTurnHandler(){
        if (this.turnHandlerTimer) {
            clearInterval(this.turnHandlerTimer);
            this.turnHandlerTimer = null;
        }
    }

    _turnSteerToZero(){
        let isLast = false;
        if (this.realTotalRotationCCW > 0) {
            this.realTotalRotationCCW -= this.realTotalRotationCCW > 45 ? 2 : 1;
            if (this.realTotalRotationCCW <= 0) {
                this.realTotalRotationCCW = 0;
                if (this.turnHandlerTimer) {
                    clearInterval(this.turnHandlerTimer);
                    this.turnHandlerTimer = null;
                }
                isLast = true;
            }
        } else if (this.realTotalRotationCCW < 0) {
            this.realTotalRotationCCW += this.realTotalRotationCCW < -45 ? 2 : 1;
            if (this.realTotalRotationCCW >= 0) {
                this.realTotalRotationCCW = 0;
                if (this.turnHandlerTimer) {
                    clearInterval(this.turnHandlerTimer);
                    this.turnHandlerTimer = null;
                }
                isLast = true;
            }
        } else {
            isLast = true;
        }
        this.totalRotationCCW = this.realTotalRotationCCW;
        this._onMoveCirclesProcess(this.realTotalRotationCCW);
        this._onMoveKnobSet(this.realTotalRotationCCW);

        return isLast;
    }

    /**
     * Function for starting the auto turn back to zero of the steering wheel after the touch is released.
     * For switch off set stepBackActive = false
     */
    _startAutoTurnBack(){
        this._stopTurnHandler();
        if (!this.isTurning) {
            if (this.stepBackActive) {
                if (this.realTotalRotationCCW !== 0) {
                    // Turn back to zero if stepBackDegree is set
                    this.turnHandlerTimer = setInterval(() => {
                        if (this._turnSteerToZero()) {
                            this._setNewSteerNoWait(0);
                            this._stopTurnHandler();
                        } else {
                            this._setNewSteer(this.realTotalRotationCCW);
                        }
                    }, this.stepBackPeriodMs);
                }
            } else {
                this._sendSteerValToCb(0); // stop control by joystick
                // Turn according real hardware rotation
                this.turnHandlerTimer = setInterval(() => {
                    this.totalRotationCCW = this.realHardwareRotationCCW;
                    this._turnHandlerProcess(2);
                }, 10);
            }
        }
    }

    /**
     * Support function for turning the steering wheel.
     * It is available only when the steering wheel is turned.
     * For set speed of turning use stepDegreePerSec.
     */
    _turnHandlerProcess(step){
        const dRot = this.totalRotationCCW - this.realTotalRotationCCW;
        if (dRot < 0) {
            this.realTotalRotationCCW -= step;
            if (this.realTotalRotationCCW < this.totalRotationCCW) {
                this.realTotalRotationCCW = this.totalRotationCCW;
            }
            this._onMoveCirclesProcess(this.realTotalRotationCCW);
            this._onMoveKnobSet(this.realTotalRotationCCW);
        } else if (dRot > 0) {
            this.realTotalRotationCCW += step;
            if (this.realTotalRotationCCW > this.totalRotationCCW) {
                this.realTotalRotationCCW = this.totalRotationCCW;
            }
            this._onMoveCirclesProcess(this.realTotalRotationCCW);
            this._onMoveKnobSet(this.realTotalRotationCCW);
        }
    }

    /**
     * Function for starting the turn handler by time Interval.
     * It is used for smooth turning of the steering wheel according to the set speed and touch values.
     * For set speed of turning use stepDegreePerSec.
     */
    _startTurnHandler (){
        this._stopTurnHandler();
        if (this.isTurning) {
            if (this.totalRotationCCW !== this.realTotalRotationCCW) {
                this._printLog('Start turn handler with stepDegreePerSec.');
                this.turnHandlerTimer = setInterval(() => {
                    if (this.totalRotationCCW !== this.realTotalRotationCCW) {
                        this._turnHandlerProcess(1);
                    } else {
                        // Restart handler with lower frequency
                        this._stopTurnHandler();
                        this._startTurnHandler();
                    }
                    this._setNewSteer(this.realTotalRotationCCW);
                    if (!this.isTurning) {
                        this._stopTurnHandler();
                    }
                }, this.stepDegreePerSec);
                    // const tick = (t) => {
                    // const dt = this._lastTs ? (t - this._lastTs) : 16;
                    // this._lastTs = t;
                    // const step = Math.max(1, dt / (1000 / (this.stepDegreePerSec ? 1000/this.stepDegreePerSec : 60)));
                    // if (this.totalRotationCCW !== this.realTotalRotationCCW) {
                    //   this._turnHandlerProcess(step);
                    // }
                    // this._setNewSteer(this.realTotalRotationCCW);
                    // if (this.isTurning) this._raf = requestAnimationFrame(tick);
                    // };
                    // cancelAnimationFrame(this._raf);
                    // this._raf = requestAnimationFrame(tick);
            } else {
                this._printLog('Start turn handler with 50ms interval.');
                this.turnHandlerTimer = setInterval(() => {
                    if (this.totalRotationCCW !== this.realTotalRotationCCW) {
                        this._turnHandlerProcess(1);
                        // Restart handler with higher frequency
                        this._stopTurnHandler();
                        this._startTurnHandler();
                    }
                    this._setNewSteer(this.realTotalRotationCCW);
                    if (!this.isTurning) {
                        this._stopTurnHandler();
                    }
                }, 50);
            }
        }
    }

    /**
     * Function for setting the inner and outer circles
     * @param valIn - percent for the inner circle
     * @param valOut - percent for the outer circle
     */
    _setInOutCircles(valIn, valOut){
        this.steerInnerCircle.style.setProperty('--fill-percent-second', valIn);
        this.steerOuterCircle.style.setProperty('--fill-percent-second', valOut);
    }

    _resetCenterCircle(){
        this.steerCenterCircle.style.display = 'block';
        this.steerCenterCircle.classList.remove('right');
        this.steerCenterCircle.classList.remove('left');
        this.steerCenterCircle.style.setProperty('--fill-percent-first', '0%');
    }
    _setCircleFillToZero(){
        this.steerInnerCircle.style.display = 'block';
        this.steerOuterCircle.style.display = 'block';
        this._setInOutCircles('0%', '100%');
        this._resetCenterCircle();
    }

    /**
     *  Functions for updating the circles in positive directions
     * @param fillPercent1 - percent for the center circle
     * @param fillPercent2 - percent for the outer circle
     */
    _updateCircleFillLeftPositive(fillPercent1,  fillPercent2){
        if (fillPercent2 === 0) {
            if (this.lastFiilState !== 1) {
                this._setCircleFillToZero();
                this.steerCenterCircle.classList.remove('right');
                this.steerCenterCircle.classList.add('left');
                this.lastFiilState = 1;
            }
            if (fillPercent1 === 0){
                this._resetCenterCircle();
                this.lastFiilState = 0;
            }else{
                this.steerCenterCircle.style.setProperty('--fill-percent-first', `${100 - fillPercent1}%`);
            }
        }else {
            if (this.lastFiilState !== 2) {
                this.steerCenterCircle.classList.remove('right');
                this.steerCenterCircle.classList.add('left');
                this.steerCenterCircle.style.setProperty('--fill-percent-first', `0%`);
                this.lastFiilState = 2;
            }

            this._setInOutCircles('0%', `${100 - fillPercent2}%`);
        }
    };

    /**
     *  Functions for updating the circles in negative directions
     * @param fillPercent1 - percent for the center circle
     * @param fillPercent2 - percent for the inner circle
     */
    _updateCircleFillRightNeget(fillPercent1,  fillPercent2){
        if (fillPercent2 === 0) {

            if (this.lastFiilState !== -1) {
                this._setCircleFillToZero();
                this.steerCenterCircle.classList.remove('left');
                this.steerCenterCircle.classList.add('right');
                this.lastFiilState = -1;
            }
            if (fillPercent1 === 0){
                this._resetCenterCircle();
            }else {
                this.steerCenterCircle.style.setProperty('--fill-percent-first', `${fillPercent1}%`);
            }

        }else {
            if (this.lastFiilState !== -2) {
                this.steerCenterCircle.classList.remove('left');
                this.steerCenterCircle.classList.add('right');
                this.steerCenterCircle.style.setProperty('--fill-percent-first', `100%`);
                this.lastFiilState = -2;
            }

            this._setInOutCircles(`${fillPercent2}%`, '100%');
        }
    };


    /**
     * Function for updating the circles visually
     * @param rotation - rotation angle in full range
     */
    _onMoveCirclesProcess(rotation){
        if (!this.isUsingColorCircles || this.lastRotationCCW === rotation) {
            return;
        }
        if (rotation <= 0) {
            if (rotation >=- 360) {
                this._updateCircleFillLeftPositive(-rotation/360 *100, 0);
            } else {
                this._updateCircleFillLeftPositive(100, (-rotation - 360)/360*100);
            }

        }else {
            if (rotation <360) {
                this._updateCircleFillRightNeget(rotation/360*100, 0);
            }else{
                this._updateCircleFillRightNeget(100, (rotation - 360)/360*100);
            }
        }

        this.lastRotationCCW = rotation;

    }

    /**
     * Function for updating the knob position
     * @param steerAngle - angle of the steering wheel
     */
    _onMoveKnobSet(steerAngle){

        this.steerCircleImage.style.transform = `rotate(${steerAngle % 360}deg)`;
        this.knobWrap.style.transform = `rotate(${steerAngle % 360}deg)`;

        this._setSteerAngleInInfo(steerAngle);

    }

    _setSteerAngleInInfo(steerAngle){
        if (this.isInfoFrameActive) {
            const steerAngleFixed = steerAngle * (this.counterClockwiseMode ? 1.0 : -1.0);
            this.steerInfo.innerText = `∠ ${steerAngleFixed.toFixed(0)}°`;
            this._printLog('Steer Info updated: ∠ ' + steerAngle +'/' + steerAngleFixed.toFixed(0) + '°');
        }
    }

    /**
     * Function for setting the initial position of the circle
     * @returns {number} - width of the circle
     */
    _setCircleInitialPos(circleWidthVal= null){
        const rect = this.steerMainCircle.getBoundingClientRect();
        const rectArea = this.joystickContainer.getBoundingClientRect();

        let circleWidth = circleWidthVal || rect.width;

        if (circleWidth < rectArea.width * 0.3) {
            circleWidth = rectArea.width * 0.3;
        }

        const minLeft = rectArea.left + circleWidth * 0.7;
        const maxLeft = rectArea.right - circleWidth * 0.7;
        const minTop = rectArea.top + circleWidth * 0.7;
        const maxTop = rectArea.bottom - circleWidth * 0.6;

        if (this.centerX < minLeft) {
            this.centerX = minLeft;
        } else if (this.centerX > maxLeft) {
            this.centerX = maxLeft;
        }
        if (this.centerY < minTop) {
            this.centerY = minTop;
        }else if (this.centerY > maxTop) {
            this.centerY = maxTop;
        }

        const xCircle = this.centerX - rectArea.left;
        const yCircle = this.centerY - rectArea.top;


        this.steerMainCircle.style.left = `${ xCircle }px`;
        this.steerMainCircle.style.top = `${yCircle }px`;

        return circleWidth;
    }

    /**
     * Function for getting the current angle pointed on the circle
     * @param dx - difference
     * @param dy - difference
     * @returns {number} - angle in degrees
     */
    _getCurrAngle(dx, dy){
        let currentAngle = Math.atan2(dy, dx) * (180 / Math.PI) + 90; // Верх = 0 градусов
        currentAngle = (currentAngle + 360) % 360;
        return currentAngle;
    }

    getTargetTouch(event, targetIdentifier) {
        if (targetIdentifier) {
            const touches = event.touches || [event];
            for (const touch of touches) {
                const identifier = touch.identifier !== undefined ? touch.identifier : 'mouse';
                if (identifier === targetIdentifier) {
                    return touch;
                }
            }
            this._printLog('Target touch not found for identifier:', targetIdentifier);
        }
        return null;
    }

    _getTouchIdentifier(event) {
        const touches = event.changedTouches || [event];
        if (touches.length > 0) {
            return  touches[0].identifier !== undefined ? touches[0].identifier : 'mouse';
        }
        this._printLog('No touches found in event to get identifier.');
        return null;
    }

    /**
     * Function for the first initialization of the circle - on appearance
     */
    _onFirstInit(){
        this.realTotalRotationCCW = this.totalRotationCCW = 0;

        const steerWidth = this._setCircleInitialPos();

        this.radius = steerWidth / 2; // Предполагаем, что круг квадратный

        this._onMoveCirclesProcess(0);
        this._onMoveKnobSet(0);

        this._setCircleFillToZero();
    }

    /**
     * Function initialization on next touches to the circle
     * @param x
     * @param y
     * @returns {boolean} - true if it will be handled moving
     */
    _onSecondInitCheckCenter(x, y){
        const dx = x - this.centerX;
        const dy = y - this.centerY;
        let currentAngle = this._getCurrAngle(dx, dy);

        this.totalRotationCCW = this.realTotalRotationCCW;

        const distance = Math.sqrt(dx * dx + dy * dy);
        let isHandleNext = true;
        if (distance <= this.radius * 1.5) {
            if (distance >= this.radius *0.4) {
                this.lastAngle = currentAngle;
            } else{
                if (this.onCenterPressed){
                    this.onCenterPressed();
                    isHandleNext = false;
                }
            }
        }

        return isHandleNext;
    }

    // ===== external uses =====
    /**
     * Function for setting the joystick enable or disable - to show or hide
     * @param isEnable - true for enable, false for disable
     */
    setJoystickEnable(isEnable){
        if (isEnable){
            this.joystickContainer.classList.add('visible');
            this.isJoystickActive = true;
        } else{
            this.isJoystickActive = false;
            this.hideJoystick();
            this.joystickContainer.classList.remove('visible');
        }
        console.log('Steering Wheel Joystick isEnable:', isEnable);
    }

    placeSteerJoyOnInit() {
        let circleWidthVal = null;
        let x = 0;
        let y = 0;
        //if (this.steerMainCircle.classList.contains('visible')) {
            const rectArea = this.joystickContainer.getBoundingClientRect();
            circleWidthVal = rectArea.width * 0.3;
            x = this.isLeftPosition ? rectArea.left + circleWidthVal * 1.5 : rectArea.right - circleWidthVal * 1.5;
            y = rectArea.top + rectArea.height * 0.4;
            this._printLog('Placing joystick on init at:', x, y);
        // }else {
        //     this._printLog('Joystick already visible, no placing on init.');
        //     return;
        // }
        this._firstPlacing(x, y, circleWidthVal);

    }

    setJoystickActive(isActive){
         this.isJoystickActive = isActive;
        console.log('Steering Wheel Joystick isActive:', isActive);
    }

    hideJoystick(){
        this.steerMainCircle.classList.remove('active');
        this.steerMainCircle.classList.remove('visible');
        this.circleTransEnd = false;
        this._printLog('Joystick hidden.');
    }

    /**
     * Function for setting the visibility of the information frame
     * @param isVisible
     */
    setInfoVisible(isVisible){
        this.isInfoFrameActive = isVisible;
        this.steerInfo.style.display = isVisible ? 'block' : 'none';
    }

    isInfoVisible(){
        return this.isInfoFrameActive;
    }

    toggleStepBackActive(){
        this.stepBackActive = !this.stepBackActive;
        if (!this.isTurning) {
            this._printLog('Step back active toggled to:', this.stepBackActive);
            this._startAutoTurnBack();
        }
    }


    manualActiveSteer(isActive){
        if (this.isTurning !== isActive) {
            this._printLog('Manual active steer set to:', isActive);
            if (isActive) {
                this.isTurning = true;
                this._startTurnHandler();
            } else {
                this.isTurning = false;
                this._startAutoTurnBack();
            }
        }
    }

    /**
     * Function for setting the new steering angle from external sources
     * @param steerAngle - angle of the steering wheel
     * @param isCCW - true for counterClockwiseMode, false for clockwise
     */
    externalSetNewSteer(steerAngle, isCCW= true){
        let fixedSteerAngle = steerAngle  * (isCCW ? 1 : -1);
        this.totalRotationCCW = this.realTotalRotationCCW = fixedSteerAngle;
        this._onMoveCirclesProcess(fixedSteerAngle);
        this._onMoveKnobSet(fixedSteerAngle);
        this._setNewSteer(fixedSteerAngle);
        this._printLog('External set new steer angle to:', fixedSteerAngle);
    }

    manualSteerAdd(deltaAngle, isCCW = true){
        this.totalRotationCCW += deltaAngle * (isCCW ? 1 : -1);
        this.totalRotationCCW = Math.max(-this.maxRotationAngle, Math.min(this.maxRotationAngle, this.totalRotationCCW));
        this._startTurnHandler();
        this._printLog('Manual steer add by:', deltaAngle * (isCCW ? 1 : -1), ' new totalRotationCCW:', this.totalRotationCCW);
    }

    setHardwareSteerAngle(steerAngle, isCCW = true){
        this.realHardwareRotationCCW = steerAngle * (isCCW ? 1 : -1);
        if (this.steerHarwareCircle){
            this.steerHarwareCircle.style.display = 'flex';
            this.steerHarwareCircle.style.transform = `rotate(${this.realHardwareRotationCCW % 360}deg)`;
            this._printLog('Set hardware steer angle to:', this.realHardwareRotationCCW);
        }

    }

    /* CCW - counterClockwiseMode, CW - clockwise */
    getSteerPercent(isCCW = true) {
        return (this.realTotalRotationCCW * (isCCW ? 1 : -1)) / this.maxRotationAngle;
    }
    getSteerAngle(isCCW = true) {
        return this.realTotalRotationCCW * (isCCW ? 1 : -1);
    }

}
