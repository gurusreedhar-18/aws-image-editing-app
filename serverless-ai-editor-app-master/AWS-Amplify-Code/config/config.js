// Replace the placeholder values below with your actual AWS resource identifiers
// 
// Instructions:
// 1. Replace 'REPLACE_WITH_YOUR_USER_POOL_ID' with your Cognito User Pool ID
//    Example: us-west-2_uXboG5pAb
//    Find this in: AWS Console > Cognito > User Pools > [Your Pool] > General Settings
//
// 2. Replace 'REPLACE_WITH_YOUR_CLIENT_ID' with your Cognito App Client ID  
//    Example: 25ddkmj4v6hfsfvruhpfi7n4hv
//    Find this in: AWS Console > Cognito > User Pools > [Your Pool] > App Clients
//
// 3. Replace 'REPLACE_WITH_YOUR_REGION' with your AWS region
//    Example: us-west-2, us-east-1, eu-west-1
//
// 4. Replace 'REPLACE_WITH_YOUR_API_URL' with your API Gateway endpoint
//    Example: https://abc123def.execute-api.us-west-2.amazonaws.com/prod
//    Find this in: AWS Console > API Gateway > [Your API] > Stages > [Stage Name]

window._workshopConfig = {
  cognito: {
    userPoolId: 'us-east-1_QmeM8lPLh', // e.g. us-west-2_uXboG5pAb
    userPoolClientId: '4bkt9vu7vhmj02pskp9rg0c6ir', // e.g. 25ddkmj4v6hfsfvruhpfi7n4hv
    region: 'us-east-1' // e.g. us-west-2
  },
  api: {
    invokeUrl: 'https://tkpyisoqgd.execute-api.us-east-1.amazonaws.com/dev' // e.g. https://abc123def.execute-api.us-west-2.amazonaws.com/prod
  }
};

// Configuration validation flag
window._configLoaded = true;
