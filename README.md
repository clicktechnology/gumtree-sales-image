# Introduction

Developing Lambda functions in the console is fine for "Hello world!" type demonstrations. If however, you want to be able to ..

- Develop code locally
- Test code locally
- Use your favourite IDE
- Use Git to manage code build versions and then create Docker images for use in prod

.. then you need to use a local development environment.

The project I did here was to simply count the number of items for sale on gumtree.com within a one mile radius of where I live in Broadstone, Dorset, and then produce hourly, daily, weekly, monthly and yearly graphs using rrdtool.

## Build status

[![Build and deploy Lambda function image](https://github.com/clicktechnology/gumtree-sales-image/actions/workflows/build-and-deploy.yml/badge.svg)](https://github.com/clicktechnology/gumtree-sales-image/actions/workflows/build-and-deploy.yml)

## Why do this?

I wanted to see if it's possible to see any trends in the data. For example, are there more items for sale on a Sunday than a Monday? Are there any economic trends? More people moving house? More people buying/selling? Could, for example, number of freebie sofas for sale be indicative of people moving out of the area? If so, what's the baseline, and so on?

I then thought it'd be interesting to use AWS Lambda to do this as it runs for under 15 minutes and is serverless and essentially free computing.

I then wondered how it would work if I used a Docker image for the Lambda function and so the process of developing the widget began.

## How does it work?

The code should run as a Python 3.11 Lambda function, contained in a Docker image, hosted at the AWS Elastic Container Registry. The Lambda function uses the image and code therein to run the function. The function is triggered by a scheduled CloudWatch event every 10 minutes.

As a side note, <http://www.cloudguyinbroadstone.com> is a Hugo blog site using an S3 bucket for the site and CloudFront for the CDN.

When the lambda function runs, it gets the gumtree.com URI, parses the response for the total number of items for sale and then writes the data to an rrdtool database. The rrdtool database is then used to create graphs.
The graphs and database are uploaded to S3 and then the CloudFront cache is invalidated for the graph images so that CloudFront will fetch the new images from S3.

The following entries are the cut-and-paste code from the AWS CLI. In the real world, you'd use a CI/CD pipeline to build the Docker image and deploy it to AWS. The CLIs are super useful to get a feel for the process though.

## RRD file creation

The RRD file is created using the following command:

```bash
rrdtool create items.rrd --start N --step 600 DS:sale-count:GAUGE:1200:U:U RRA:AVERAGE:0.5:1:10080 RRA:MAX:0.5:6:12960 RRA:MIN:0.5:6:12960
```

## Set the variables

Set the variables

```bash
LAMBDA_NAME='gumtree-sales'
LAMBDA_VER='1.1.2'
LAMBDA_LOCAL_PORT=19000
REGION='eu-west-2'
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
REPO="${LAMBDA_NAME}"
TAG="${LAMBDA_VER}"
CLOUDFRONT_DISTRIBUTION='E235IO7SVJ19TF'
RRD_FILE='items.rrd'
CSV_FILE='sales-count.csv'
GUMTREE_URL='https://www.gumtree.com/search?featured_filter=false&q=&search_location=Broadstone%2C+Dorset&search_category=for-sale&distance=1&urgent_filter=false&sort=date&search_distance=1&search_scope=false&photos_filter=false'
S3_BUCKET='www.cloudguyinbroadstone.com'
```

## Log in to the ECR

```bash
aws ecr get-login-password --region ${REGION} | \
docker login -u AWS --password-stdin "https://${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
```

## Build the image

Chose one or other of the following commands according to taste. The latter is very much faster.

### Build the image from scratch

```bash
DOCKER_BUILDKIT=0 && docker build --pull --no-cache --platform linux/amd64 -t ${REPO}:${TAG} .
```

### Alternatively, build the image, don't rebuild everything

```bash
DOCKER_BUILDKIT=0 && docker build --platform linux/amd64 -t ${REPO}:${TAG} .
```

## Test the image

Start the function locally

```bash
docker run -p ${LAMBDA_LOCAL_PORT}:8080 ${REPO}:${TAG}
```

Fire a request at the function to test it. In the first case, we're not passing any data to the function. In the second case, we're passing some data to the function which I used for testing and you may want to experiment. For the Gumtree project, there is no inbound data, so the first example is the one to use.

```bash
curl -d "int_temp=21&ext_temp=3&rh=72" -X POST http://172.17.0.3:8080/data
```

## Tag the image

Self explanatory.

```bash
docker tag ${REPO}:${TAG} ${REGISTRY}/${REPO}:${TAG}
```

## Push the local image ECR repo and tag with the current tag

Now let's push the image to ECR. The following command pushes the image to ECR.

```bash
docker push ${REGISTRY}/${REPO}:${TAG}
```

## Add a 'latest' tag

In addition to the version tag, also add the 'latest' tag to the image

```bash
MANIFEST=$(aws ecr batch-get-image --repository-name ${REPO} \
--image-ids imageTag=${TAG} \
--query 'images[].imageManifest' \
--output text)
aws ecr put-image --repository-name ${REPO} --image-tag latest --image-manifest "$MANIFEST"
```

## IAM Policies and Roles

To run the Lambda function, I created a policy called `AWSLambdaBasicExecutionPolicy-gumtree-sales`, below.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": ["*"]
    },
    {
      "Effect": "Allow",
      "Action": ["cloudfront:CreateInvalidation"],
      "Resource": [
        "arn:aws:cloudfront::123456789012:distribution/E235IO7SVJ19TF"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::cloudguyinbroadstone",
        "arn:aws:s3:::cloudguyinbroadstone/*"
      ]
    }
  ]
}
```

I then created a role called `AWSLambdaBasicExecutionRole-gumtree-sales` (Trusted entity - AWS Service: lambda) and attached the `AWSLambdaBasicExecutionPolicy-gumtree-sales` policy above to it.

## Create the lambda function

Now we can create the lambda function. The following command deletes the function if present and then creates the function, using the image we just pushed to ECR.

```bash
aws lambda delete-function --function-name ${LAMBDA_NAME}
aws lambda create-function \
  --code ImageUri=${REGISTRY}/${REPO}:latest \
  --description "Count of number of items for sale near Broadstone" \
  --environment Variables="{CLOUDFRONT_DISTRIBUTION=${CLOUDFRONT_DISTRIBUTION},RRD_FILE=${RRD_FILE},CSV_FILE=${CSV_FILE},GUMTREE_URL=${GUMTREE_URL},S3_BUCKET=${S3_BUCKET}}" \
  --function-name ${LAMBDA_NAME} \
  --timeout 30 \
  --package-type Image \
  --role "arn:aws:iam::${ACCOUNT_ID}:role/AWSLambdaBasicExecutionRole-${LAMBDA_NAME}"
```

## Results

The final result is five graphs of the number of items for sale on Gumtree in Broadstone, Dorset within 1 mile.

The article about this is [here](http://www.cloudguyinbroadstone.com/posts/for-sale/) and the [final results are here](http://www.cloudguyinbroadstone.com/posts/for-sale/#output).
