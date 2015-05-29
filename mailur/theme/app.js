var ws = null, handlers = {};

// Ref: http://stackoverflow.com/questions/105034/create-guid-uuid-in-javascript
function guid() {
    var d = new Date().getTime();
    var uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(
        /[xy]/g,
        function(c) {
            var r = (d + Math.random() * 16) % 16 | 0;
            d = Math.floor(d / 16);
            return (c == 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
    return uuid;
}
function connect() {
    ws = new WebSocket('ws://localhost:5001');
    ws.onopen = function() {
        console.log('ws opened');
    };
    ws.onmessage = function(e) {
        data = JSON.parse(e.data);
        if (data.uid) {
            console.log('response for ' + data.uid);
            var handler = handlers[data.uid];
            if (handler) {
                handler(data.payload);
            }
        } else if (data.updated) {
            console.log(data);
            var path = window.location.pathname;
            send(path + '?fmt=body', null, function(data) {
                if (path.search('^/thread/') != -1) {
                    updateEmails(data, true);
                } else if (path.search('^/in/') != -1) {
                    updateEmails(data);
                } else {
                    $('body').html(data);
                }
            });
        }
    };
    ws.onclose = function() {
        console.log('ws closed');
        setTimeout(connect, 10000);
    };
}
function send(url, data, callback) {
    if (ws === null) {
        connect();
        send(url, data, callback);
    } else {
        url = 'http://localhost:5000' + url;
        var resp = {url: url, payload: data, uid: guid()};
        ws.send(JSON.stringify(resp));
        if (callback) {
            handlers[resp.uid] = callback;
        }
    }
}
function updateEmails(data, thread) {
    var container = $('.emails');
    $(data).find('.email').each(function() {
        var $this = $(this);
        var exists = $('#' + $this.attr('id'));
        if (exists.length && $this.data('hash') != exists.data('hash')) {
            exists.replaceWith(this);
        } else if (!exists.length) {
            if (thread) {
                container.append(this);
            } else {
                container.prepend(this);
            }
        }
    });
}

connect();
$('.thread .email-info').click(function() {
    var email = $(this).parents('.email');
    email.toggleClass('email-show');
    if (email.hasClass('email-show') && !email.hasClass('email-loaded')) {
        send(email.data('body-url'), null, function(data) {
            email.find('.email-body').html(data);
            email.addClass('email-loaded');
        });
    }
    return false;
});
$('.thread').on('click', ' .email-details-toggle', function() {
    $(this).parents('.email').find('.email-details').toggle();
    return false;
});
$('.email').on('click', '.email-quote-toggle', function() {
    $(this).next('.email-quote').toggle();
    return false;
});
$('.email').on('click', '.email-pin', function() {
    var email = $(this).parents('.email');
    var id = email.data('id');
    var action = email.hasClass('email-pinned') ? 'rm' : 'add';
    send('/mark/', {ids: [id], name: '\\Starred', action: action});
    return false;
});
