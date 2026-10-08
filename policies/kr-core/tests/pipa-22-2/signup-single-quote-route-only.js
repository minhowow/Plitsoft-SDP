const http = require('./http');

function submit(email, birthDate) {
  return http.post('/signup', { email, birthDate });
}

module.exports = { submit };
