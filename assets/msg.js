import Vue from 'vue';
import tpl from './msg.html';

Vue.component('msg', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    thread: { type: Boolean, default: false },
    detailed: { type: Boolean, default: false },
    picked: { type: Boolean, default: false },
    details: {type: Function },
    pick: {type: Function },
    hideSubj: { type: Function, default: () => false }
  },
  methods: {
    fetch: q => window.app.fetch(q),
    open: function() {
      if (this.thread) {
        this.fetch(this.msg.query_thread);
      } else {
        this.details(this.msg.uid);
      }
    },
    openInSplit: function() {
      window.app.openInSplit(this.msg.query_thread);
    }
  }
});