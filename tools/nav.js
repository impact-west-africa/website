// The mobile menu is a <details>, so it closes on its own when a link
// navigates away. It does not close when the link is a #fragment on the page
// already loaded - no navigation happens, so the panel stays open over the
// section the visitor just asked for. Close it by hand on any link tap.
//
// Without this script the menu still opens and closes from its own button;
// only the tap-a-link-to-close shortcut is missing.
(function () {
  var head = document.querySelector('.site-head');
  if (!head || !document.documentElement.closest) return;

  head.addEventListener('click', function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    // Taps on the +/- of a section accordion are not links, and must keep
    // working as toggles.
    if (!target.closest('a[href]')) return;
    var open = head.querySelectorAll('details[open]');
    for (var i = 0; i < open.length; i++) open[i].open = false;
  });
})();
