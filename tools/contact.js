// Contact form -> Formspree, submitted over fetch so the page can swap in the
// "thank you" panel from the design instead of navigating away. The form also
// works without JS: it is a plain POST to the same endpoint, and Formspree
// renders its own confirmation page.
(function () {
  var form = document.getElementById('contact-form');
  var sent = document.getElementById('contact-sent');
  if (!form || !sent || !window.fetch) return;

  var button = form.querySelector('button[type="submit"]');
  var label = button ? button.textContent : '';

  function fail() {
    var note = form.querySelector('.form-error');
    if (!note) {
      note = document.createElement('p');
      note.className = 'form-error';
      note.style.cssText =
        'margin:0;font-size:14px;line-height:1.7;color:#a55229';
      note.innerHTML =
        'Something went wrong sending your message. Please email us at ' +
        '<a href="mailto:info@impactwestafrica.org" ' +
        'style="border-bottom:1px solid rgba(165,82,41,0.4)">' +
        'info@impactwestafrica.org</a> instead.';
      form.appendChild(note);
    }
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    if (button) {
      button.disabled = true;
      button.textContent = 'Sending…';
    }
    fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: { Accept: 'application/json' }
    })
      .then(function (response) {
        if (!response.ok) throw new Error(response.status);
        // The form carries an inline `display:grid`, which outranks the
        // UA's [hidden] rule - hide it by style, not by the attribute.
        form.style.display = 'none';
        form.hidden = true;
        sent.hidden = false;
        sent.setAttribute('tabindex', '-1');
        sent.focus();
      })
      .catch(function () {
        fail();
        if (button) {
          button.disabled = false;
          button.textContent = label;
        }
      });
  });
})();
