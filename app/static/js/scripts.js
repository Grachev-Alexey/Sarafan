$(document).ready(function () {
    // Показать/скрыть пароль
    $('.toggle-password').click(function () {
        const input = $(this).parent().prev();
        if (input.attr('type') === 'password') {
            input.attr('type', 'text');
            $(this).html('<i class="fas fa-eye-slash"></i>');
        } else {
            input.attr('type', 'password');
            $(this).html('<i class="fas fa-eye"></i>');
        }
    });

    // Копирование реферальной ссылки
    new ClipboardJS('.copy-button');
});