export class SliderController {
    constructor() {
        this.sliders = {}; // Зарегистрированные слайдеры
        this.activeSliders = {}; // Активные касания

        // Общие обработчики событий
        this.handleMove = this.handleMove.bind(this);
        this.handleUp = this.handleUp.bind(this);
        // Подписка на события
        if (!('ontouchstart' in window)) {
            document.addEventListener('mousemove', (e) => this.handleMove(e), {passive: false});
            document.addEventListener('mouseup', (e) => this.handleUp(e), {passive: false});
        }
        document.addEventListener('touchmove', (e) => this.handleMove(e), {passive: false});

        document.addEventListener('touchend', (e) => this.handleUp(e), {passive: false});
        document.addEventListener('touchcancel', (e) => this.handleUp(e), {passive: false});
    }


    /**
     * Регистрация слайдера
     * @param {string} sliderId - ID контейнера слайдера
     * @param {string} knobId - ID ручки слайдера
     * @param {object} options - Опции слайдера
     */
    registerSlider(sliderId, knobId, options = {}) {
        const slider = document.getElementById(sliderId);
        const knob = document.getElementById(knobId);

        if (!slider || !knob) {
            console.error(`Can't find slider or knob with ID: ${sliderId} or ${knobId}`);
            return;
        }
        knob.addEventListener('dragstart', (event) => {
            event.preventDefault();
            console.log('Drag is not allowed');
        });

        const sliderRect = slider.getBoundingClientRect();

        const item = {
            sliderId,
            slider,
            knob,
            _cached: {
                left: sliderRect.left,
                top: sliderRect.top,
                width: sliderRect.width,
                height: sliderRect.height
            },
            _raf: null,
            _queuedPercent: null,
            options: {
                isVerticalSlider: options.isVerticalSlider || false,
                minPositionPercent: (options.minPosition ?? 0),
                maxPositionPercent: (options.maxPosition ?? 100),
                initialPositionPercent:  (options.initialPositionPercent ?? 0),
                activateDelay: options.activateDelay || 0, // Задержка активации (в мс)
                deactivateDelay: options.deactivateDelay || 0, // Задержка деактивации (в мс)
                onPressed: options.onPressed || null, // Обработчик нажатия - возвращает true, если обработка должна продолжиться
                onDragStart: options.onDragStart || null, // Обработчик начала перетаскивания
                periodicTaskOnPressed: options.periodicTaskOnPressed || null, // Обработчик перемещения
                funcHandleOnMove: options.funcHandleOnMove || null, // Обработчик перемещения
                periodicTaskOnPressedInterval: options.periodicTaskOnPressedInterval || 100, //  Обработчик перемещения
                onProgress: options.onProgress || null, //  Обработчик перемещения
                onStateChange: options.onStateChange || null, // Обработчик состояния
                onDragEnd: options.onDragEnd || null, // Обработчик окончания перетаскивания
                isStopPropagation: options.isStopPropagation || false, // Блокировка всплытия события

                holdTimeout: null, // Таймер удержания
                periodicTaskTimer: null, // Таймер периодической задачи
                periodicTaskTimerStamp: 0, // Шт
                isDragging: false,
                isMoveStarted: false,
                startX: 0, // Смещение мыши от начала ручки
                startY: 0, // Смещение мыши от начала ручки
                clientX: 0, // Координаты клиента
                clientY: 0, // Координаты клиента
            },
        };

        this.sliders[sliderId] = item;

        //item.options.initialPositionPercent

        console.log('registerSlider: ' + sliderId + " knobId: " + knobId + '; isVerticalSlider '
            + item.options.isVerticalSlider
            + '; minPosition: ' + item.options.minPositionPercent + '; maxPosition: ' + item.options.maxPositionPercent);
        // Добавляем слайдер в список

        // Привязка событий
        if (!('ontouchstart' in window)) {
            knob.addEventListener('mousedown', (e) => this.handleStart(e, sliderId));
        }
        knob.addEventListener('touchstart', (e) => this.handleStart(e, sliderId));

        return sliderId;
    }


    isEmptyTouches() {
        return Object.keys(this.activeSliders).length === 0;
    }

    isEmptySliders() {
        return Object.keys(this.sliders).length === 0;
    }

    /**
     * Обработчик начала перетаскивания
     */
    handleStart(event, sliderId) {

        const touches = event.changedTouches || [event];

        for (const touch of touches) {
            const identifier = touch.identifier !== undefined ? touch.identifier : 'mouse';

            if (this.activeSliders[identifier]) {
                continue;
            }

            const activeSlider = this.sliders[sliderId];
            if (!activeSlider) return;


            activeSlider.clientX = touch.clientX;
            activeSlider.clientY = touch.clientY;
            activeSlider.isMoveStarted = false;
            activeSlider.isDragging = false;

            let clientXY = {x: touch.clientX, y: touch.clientY};

            if (this.handlePressing(activeSlider.slider, activeSlider.knob, activeSlider, clientXY, event)) {
                this.activeSliders[identifier] = activeSlider;
            }
        }

    }

    /**
     * Обработчик начала удержания
     */
    handlePressing(slider, knob, sliderData, clientXY) {

        const knobRect = knob.getBoundingClientRect();
        sliderData.startX = clientXY.x - knobRect.left - knobRect.width/2;
        sliderData.startY = clientXY.y - knobRect.top - knobRect.height/2;


        const sliderRect = slider.getBoundingClientRect();
        sliderData._cached = {
            left: sliderRect.left,
            top: sliderRect.top,
            width: sliderRect.width,
            height: sliderRect.height
        };
        if (sliderData._raf) {
          cancelAnimationFrame(sliderData._raf);
          sliderData._raf = null;
        }
        sliderData._queuedPercent = null;

        // Вызываем обработчик нажатия
        if (sliderData.options.onPressed) {
            if (!sliderData.options.onPressed(slider, knob, clientXY)) {
                return false;
            }
        }

        // Выбор времени задержки в зависимости от текущего состояния
        const isActive = slider.classList.contains('active');
        const dragDelay = isActive
            ? sliderData.options.deactivateDelay
            : sliderData.options.activateDelay;

        if (dragDelay > 0) {
            sliderData.holdTimeout = setTimeout(() => {

                // Вызываем обработчик начала перетаскивания
                sliderData.holdTimeout = null;

                if (sliderData.options.periodicTaskOnPressed) {
                    this.startPeriodicTask(slider, knob, sliderData, clientXY);
                }
                sliderData.isDragging = true;

            }, dragDelay);
        } else {
            // Если задержка 0, разрешаем немедленно
            if (sliderData.options.periodicTaskOnPressed) {
                this.startPeriodicTask(slider, knob, sliderData, clientXY);
            }
            sliderData.isDragging = true;
        }

        return true;
    }

    startPeriodicTask(slider, knob, sliderData, clientXY) {
        sliderData.periodicTaskTimerStamp = Date.now();
        if (sliderData.periodicTaskTimer !== null) {
            clearInterval(sliderData.periodicTaskTimer); // Сбрасываем таймер удержания
            sliderData.periodicTaskTimer = null;
        }
        sliderData.periodicTaskTimer = setInterval(() => {
            let duration = Date.now() - sliderData.periodicTaskTimerStamp;
            sliderData.options.periodicTaskOnPressed(slider, knob, duration, clientXY);
        }, sliderData.options.periodicTaskOnPressedInterval);
    }

    /**
     * Обработчик перемещения
     * @param event
     */
    handleMove(event) {
        const touches = event.touches || [event];

        let isStopPropagation = false;

        for (const touch of touches) {
            const identifier = touch.identifier !== undefined ? touch.identifier : 'mouse';
            const activeSlider = this.activeSliders[identifier];

            if (!activeSlider || !activeSlider.isDragging) continue;

            const dx = touch.clientX - activeSlider.clientX;
            const dy = touch.clientY - activeSlider.clientY;

            if (dx === 0 && dy === 0) {
                continue;
            }

            activeSlider.clientX = touch.clientX;
            activeSlider.clientY = touch.clientY;

            const {slider, knob, options} = activeSlider;
            isStopPropagation |= options.isStopPropagation;
            const clientXY = {x: touch.clientX, y: touch.clientY};

            // Если перетаскивание не начато, вызываем обработчик начала перетаскивания
            if (!activeSlider.isMoveStarted && activeSlider.options.onDragStart) {
                activeSlider.options.onDragStart(slider, knob, clientXY);
            }

            if (options.funcHandleOnMove) {
                options.funcHandleOnMove(slider, knob, options, clientXY);
            } else {
                this.handleOnMove(activeSlider, slider, knob, options, clientXY);
            }
            activeSlider.isMoveStarted = true;
        }

        if (isStopPropagation) {
            event.preventDefault();
        }
    }

    _setMoveSliderToPercent(sliderData, options, knob,  cached, percent) {
        sliderData._queuedPercent = percent;
        if (!sliderData._raf) {
                sliderData._raf = requestAnimationFrame(() => {
                  const p = sliderData._queuedPercent;
                  sliderData._raf = null;

                  // Преобразуем % → пиксельное смещение и двигаем ТОЛЬКО transform
                  if (!options.isVerticalSlider) {
                    const x = (p / 100) * cached.width;
                    knob.style.transform = `translate3d(${x}px, 0, 0)`;
                    console.log(`_setMoveSliderToPercent hor: ${sliderData.sliderId} percent: ${p}, x: ${x}`);
                  } else {
                    const y = ((100 - p) / 100) * cached.height;
                    knob.style.transform = `translate3d(0, ${y}px, 0)`;
                    console.log(`_setMoveSliderToPercent vert: ${sliderData.sliderId} percent: ${p}, y: ${y}`);
                  }

                  // 4) Колбэк прогресса — не чаще кадра
                  if (options.onProgress) {
                    options.onProgress(sliderData.slider, knob, p);
                  }
                });
            }
    }

    handleOnMove(sliderData, slider, knob, options, clientXY) {
        let newLeftPx; // Новая позиция в пикселях
        let newLeftPercent; // Новая позиция в процентах
        //console.log('handleOnMove '+slider.id+' : x: '+ clientXY.x + ' y: '+ clientXY.y);
        if (slider && knob) {
            const cached = sliderData._cached;
            if (!cached) return;
            let percent;
            if (!options.isVerticalSlider) {
                const px = clientXY.x - cached.left - sliderData.startX;
                percent = (px / cached.width) * 100;
            } else {
                const py = clientXY.y - cached.top - sliderData.startY;
                percent = (py / cached.height) * 100;
                percent = 100 - percent;
            }
            const clamped = Math.max(options.minPositionPercent, Math.min(percent, options.maxPositionPercent));
            this._setMoveSliderToPercent(sliderData, options, knob, cached, clamped);


            // if (!options.isVerticalSlider) {
            //
            //     // Рассчитываем новую позицию в пикселях
            //     newLeftPx = clientXY.x - cached.left - sliderData.startX;
            //     newLeftPercent = (newLeftPx / cached.width) * 100;
            //     newLeftPercent = Math.max(options.minPositionPercent, Math.min(newLeftPercent, options.maxPositionPercent)); // Ограничиваем движение в пикселях
            //
            //     // Применяем позицию в процентах
            //     knob.style.left = `${newLeftPercent}%`;
            // } else {
            //     // Рассчитываем новую позицию в пикселях
            //     newLeftPx = clientXY.y - cached.top - sliderData.startY;
            //     newLeftPercent = (newLeftPx / cached.height) * 100;
            //     newLeftPercent = Math.max(options.minPositionPercent, Math.min(newLeftPercent, options.maxPositionPercent)); // Ограничиваем движение в пикселях
            //
            //     // Применяем позицию в процентах
            //     knob.style.top = `${newLeftPercent}%`;
            //     newLeftPercent = 100 - newLeftPercent;
            //
            // }
        } else {
            newLeftPercent = 0;
        }


        // // Если есть колбэк, передаём новое значение в процентах
        // if (options.onProgress) {
        //     options.onProgress(slider, knob, newLeftPercent); // Передаём проценты
        // }
    }

    moveSliderPercent(sliderId, percent) {
        const sliderData = this.sliders[sliderId];
        if (!sliderData) return;
        const {slider, knob, options} = sliderData;

        if (slider && knob && options) {
            let clamped= Math.max(options.minPositionPercent, Math.min(percent, options.maxPositionPercent));
            // if (!options.isVerticalSlider) {
            //     clamped = Math.max(options.minPositionPercent, Math.min(percent, options.maxPositionPercent));
            // } else {
            //     clamped = 100 - Math.max(options.minPositionPercent, Math.min(percent, options.maxPositionPercent));
            // }
            this._setMoveSliderToPercent(sliderData, options, knob, sliderData._cached, clamped);
            // if (!options.isVerticalSlider) {
            //     knob.style.left = `${Math.max(options.minPositionPercent, Math.min(percent, options.maxPositionPercent))}%`;
            // } else {
            //     const perc = 100 - percent;
            //     knob.style.top = `${Math.max(options.minPositionPercent, Math.min(perc, options.maxPositionPercent))}%`;
            // }
        }
    }


    /**
     * Обработчик завершения перетаскивания
     */
    handleUpProcess(sliderData) {


        if (sliderData.holdTimeout) {
            clearTimeout(sliderData.holdTimeout); // Сбрасываем таймер удержания
            sliderData.holdTimeout = null;
        }

        if (sliderData.periodicTaskTimer !== null) {
            clearInterval(sliderData.periodicTaskTimer); // Сбрасываем таймер удержания
            sliderData.periodicTaskTimer = null;
        }

        const {slider, knob, options} = sliderData;

        if (sliderData._raf) {
          cancelAnimationFrame(sliderData._raf);
          sliderData._raf = null;
        }
        sliderData._queuedPercent = null;

        if (sliderData.isDragging && slider && knob && options && options.onStateChange) {
            // Получаем размеры слайдера
            const sliderRect = slider.getBoundingClientRect();
            const sliderWidth = sliderRect.width;

            // Получаем позицию ручки (в процентах, если указано через CSS)
            let knobPosition = 0;
            const cached = sliderData._cached;
            let percent;

            if (!options.isVerticalSlider) {
                const px = sliderData.clientX - cached.left - sliderData.startX;
                percent = (px / cached.width) * 100;
            } else {
                const py = sliderData.clientY - cached.top - sliderData.startY;
                percent = (py / cached.height) * 100;
                percent = 100 - percent;
            }
            if (sliderData.isVerticalSlider === false) {
                knobPosition = knob.style.left.includes('%')
                    ? parseFloat(knob.style.left) // Значение в процентах
                    : (parseInt(knob.style.left || options.minPositionPercent, 10) / sliderWidth) * 100; // Конвертируем из пикселей в проценты
            } else {
                knobPosition = knob.style.top.includes('%')
                    ? 100 - parseFloat(knob.style.top) // Значение в процентах
                    : 100 - (parseInt(knob.style.top || options.minPositionPercent, 10) / sliderWidth) * 100; // Конвертируем из пикселей в проценты
            }

            // Вычисляем середину в процентах
            const midpointPercent = (options.minPositionPercent + options.maxPositionPercent) / 2;

            // Проверяем активное состояние
            let isActive = knobPosition > midpointPercent;

            // Устанавливаем позицию ручки
            if (isActive) {
                knob.style.left = `${options.maxPositionPercent}%`;
            } else {
                knob.style.left = `${options.minPositionPercent}%`;
            }
            // Вызываем обработчик изменения состояния
            options.onStateChange(isActive, slider, knob);
        }


        if (options.onDragEnd) {
            options.onDragEnd(slider, knob); // Вызываем колбэк
        }

        sliderData.isDragging = false; // Сбрасываем флаг перетаскивания

    }

    handleUp(event) {

        if (event.changedTouches) {
            let isStopPropagation = false;
            for (const touch of event.changedTouches) {
                let sliderData = this.activeSliders[touch.identifier];
                if (sliderData) {
                    isStopPropagation |= sliderData.options.isStopPropagation;
                    this.handleUpProcess(sliderData);
                    sliderData.isMoveStarted = false;
                    delete this.activeSliders[touch.identifier];
                }
            }
            if (isStopPropagation) {
                event.preventDefault();
            }

        } else if (!this.isEmptyTouches()) {
            let sliderData = this.activeSliders[Object.keys(this.activeSliders)[0]];

            if (!sliderData) return;
            if (sliderData.isStopPropagation) {
                event.preventDefault();
            }
            this.handleUpProcess(sliderData);
            sliderData.isMoveStarted = false;
            delete this.activeSliders[Object.keys(this.activeSliders)[0]];
        }
    }

    // Публичные методы
    setSliderOn(sliderId) {
        const sliderData = this.sliders[sliderId];
        if (!sliderData) return;

        const {slider, knob, options} = sliderData;
        knob.style.left = `${options.maxPositionPercent}%`;
        slider.classList.add('active');
    }

    setSliderOff(sliderId) {
        const sliderData = this.sliders[sliderId];
        if (!sliderData) return;

        const {slider, knob, options} = sliderData;
        knob.style.left = `${options.minPositionPercent}%`;
        slider.classList.remove('active');
    }
}
