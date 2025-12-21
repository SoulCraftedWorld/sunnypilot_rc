// jsmain.js

// Импортируем модули проекта
import "./joystick_buttons.js";
import "./slider_controller.js";
import "./steer_wheel.js";
import "./webrtc.js";
import {onWindowResize, start, lastChannelMessageTime} from "./webrtc.js";

export var pc = null;
export var dc = null;

export const CLIENT_ID = new Date().getTime();

let logsElement = null;

// Блокируем ориентацию экрана в landscape, если поддерживается
if (screen.orientation && screen.orientation.lock) {
    screen.orientation.lock("landscape")
        .then(() => {
            console.log("Экран заблокирован в ландшафтной ориентации");
        })
        .catch((error) => {
            console.error("Не удалось заблокировать ландшафтную ориентацию:", error);
        });
} else {
    console.error("Screen Orientation API не поддерживается вашим устройством");
}

// Основная инициализация страницы
function onContentLoaded() {
    console.log("onContentLoaded");

    logsElement = document.getElementById("logs");

    // Первичная подгонка интерфейса
    onWindowResize();

    // Настройка полноэкранного режима
    const container = document.getElementById("fullscreen-container-id");
    const fullscreenButton = document.getElementById("fullscreen-button");

    if (fullscreenButton && container) {
        fullscreenButton.addEventListener("click", () => {
            console.log("fullscreenButton click");
            if (fullscreenButton.classList.contains("fullscreen")) {
                // Выход из полноэкранного режима
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                } else if (document.msExitFullscreen) {
                    document.msExitFullscreen();
                }
                fullscreenButton.classList.remove("fullscreen");
            } else {
                // Вход в полноэкранный режим
                if (container.requestFullscreen) {
                    container.requestFullscreen();
                } else if (container.webkitRequestFullscreen) {
                    container.webkitRequestFullscreen();
                } else if (container.msRequestFullscreen) {
                    container.msRequestFullscreen();
                }
                fullscreenButton.classList.add("fullscreen");
            }
        });
    }

    // Реакция на смену полноэкранного состояния
    document.addEventListener("fullscreenchange", () => {
        if (document.fullscreenElement) {
            console.log("Полноэкранный режим включен");
        } else {
            console.log("Полноэкранный режим выключен");
        }
        onWindowResize();
    });
}

// События жизненного цикла страницы
document.addEventListener("DOMContentLoaded", onContentLoaded);
window.addEventListener("resize", onWindowResize);


setInterval( () => {
  const dt = new Date().getTime();
  if ((dt - lastChannelMessageTime) > 1000) {
    $(".pre-blob").removeClass('blob');
    $("#battery").text("--");
    $("#ping-time").text('--');
    $("#speed").text('--');
    $("video")[0].load();
    $("#cruise").text("--");
  }
}, 5000);

start(pc, dc);
