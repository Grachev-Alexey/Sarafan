$(document).ready(function() {
    // Получаем flash-сообщения ДО загрузки DOM
    {% with messages = get_flashed_messages(with_categories=true) %}
        let messages = [];
        {% if messages %}
            messages = {{ messages|tojson|safe }};
        {% endif %}
    {% endwith %}

    // Используем массив messages внутри $(document).ready()
    if (messages.length > 0) {
        messages.forEach(function(message) {
            let icon = 'info';
            switch (message[0]) {
                case 'success':
                    icon = 'success';
                    break;
                case 'error':
                    icon = 'error';
                    break;
                case 'warning':
                    icon = 'warning';
                    break;
            }

            // Используем Toast вместо Swal.fire()
            const Toast = Swal.mixin({
                toast: true,
                position: "top-end",
                showConfirmButton: false,
                timer: 3000,
                timerProgressBar: true,
                didOpen: (toast) => {
                    toast.onmouseenter = Swal.stopTimer;
                    toast.onmouseleave = Swal.resumeTimer;
                }
            });

            Toast.fire({
                icon: icon,
                // title: message[0].charAt(0).toUpperCase() + message[0].slice(1), // Можно убрать или изменить title
                text: message[1]
            });
        });
    }
});