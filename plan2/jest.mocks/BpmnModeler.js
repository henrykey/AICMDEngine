class MockBpmnModeler {
  constructor(options) {
    this.options = options;
    this.listeners = {};
  }

  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }

  async importXML(xml) {
    return Promise.resolve();
  }

  async saveXML(options) {
    return Promise.resolve({ xml: '<bpmn:definitions />' });
  }

  get(service) {
    if (service === 'canvas') {
      return {
        zoom: (mode) => {},
      };
    }
    if (service === 'eventBus') {
      return this;
    }
    return {};
  }

  destroy() {}
}

module.exports = MockBpmnModeler;
