// Yash Academy - Example Configuration File
// Instructor: Yaswanth Reddy Arumulla
// Copy this to config.js and replace with your actual AWS resource identifiers

window._workshopConfig = {
  cognito: {
    userPoolId: 'us-east-1_QmeM8lPLh', // Replace with your Cognito User Pool ID
    userPoolClientId: '4bkt9vu7vhmj02pskp9rg0c6ir', // Replace with your Cognito App Client ID
    region: 'us-east-1' // Replace with your AWS region
  },
  api: {
    invokeUrl: 'https://4dcifje4wa.execute-api.us-east-1.amazonaws.com/dev' // Replace with your API Gateway URL
  }
};

window._configLoaded = true;

// Yash Academy Branding
window._YashAcademy = {
  instructor: 'Yaswanth Reddy Arumulla',
  academy: 'Yash Academy',
  youtube: 'https://www.youtube.com/@Yashacademy0',
  linkedin: 'https://www.linkedin.com/in/yaswanth-arumulla/',
  website: 'https://medium.com/@yaswanth.arumulla'
};
