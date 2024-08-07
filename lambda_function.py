import boto3
import os
import time
import requests
import rrdtool
from bs4 import BeautifulSoup
from dotenv import load_dotenv


# if running locally, load the .env file
if os.environ.get("AWS_EXECUTION_ENV") is None:
    load_dotenv()

# get the function variable values from environment variables
rrd_file = os.environ["RRD_FILE"]
csv_file = os.environ["CSV_FILE"]
distribution = os.environ["CLOUDFRONT_DISTRIBUTION"]
refresh_distribution = os.environ["REFRESH_DISTRIBUTION"]
url = os.environ["GUMTREE_URL"]
s3bucket = os.environ["S3_BUCKET"]
version = os.environ["VERSION"]

# define time periods for graphs
periods = {
    "hour": 3600,
    "day": 24 * 3600,
    "week": 7 * 24 * 3600,
    "month": 30 * 24 * 3600,  # Approximation of a month
    "year": 365 * 24 * 3600,  # Approximation of a year
}


def move_files(direction, file_array):
    """Upload or download files from S3"""
    s3 = boto3.client("s3")
    for file in file_array:
        if direction == "download":
            print("Downloading file: {}".format(file))
            s3.download_file(s3bucket, "data/" + file, "/tmp/" + file)
        elif direction == "upload":
            # if file is a graph, upload to images folder
            file_size = os.path.getsize("/tmp/" + file)
            if file.endswith("_graph.png"):
                print("Uploading graph file: {}".format(file))
                # s3.upload_file("/tmp/" + file, s3bucket, "site/images/" + file)
                response = s3.put_object(
                    Body=open("/tmp/" + file, "rb"),
                    Bucket=s3bucket,
                    Key="site/images/" + file,
                    ContentType="image/png",
                    ContentLength=file_size,
                )
            else:
                print("Uploading data file: {}".format(file))
                # s3.upload_file("/tmp/" + file, s3bucket, "data/" + file)
                response = s3.put_object(
                    Body=open("/tmp/" + file, "rb"),
                    Bucket=s3bucket,
                    Key="data/" + file,
                    ContentType="text/plain",
                    ContentLength=file_size,
                )
            print(response)


def get_item_count(uri):
    """Get the item count from the given Gumtree URI"""
    # define headers
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5)"}
    response = requests.get(uri, headers=headers)
    html_content = response.content
    soup = BeautifulSoup(html_content, "html.parser")
    h1_tag = soup.find("h1")
    number = int("".join(filter(str.isdigit, h1_tag.text)))
    if number is not None:
        return number
    else:
        return None


def update_csv(csvfile, itemcount):
    """Update the CSV file with a timestamp and the new value"""
    with open("/tmp/" + csvfile, "a") as f:
        f.write(str(int(time.time())) + "|" + str(itemcount) + "\n")
    f.close()


# main lambda handler code
def handler(event, context):
    """Main Lambda function handler"""
    print("Starting lambda function. Version: " + version)
    # download the files from S3
    move_files("download", [rrd_file, csv_file])
    # get the current item count
    item_count = get_item_count(url)

    if item_count is not None:
        # update the RRD file with the new value
        rrdtool.update("/tmp/" + rrd_file, "N:" + str(item_count))

        # update the CSV file with the new value
        update_csv(csv_file, item_count)

        # generate graphs for each time period
        for period, duration in periods.items():
            print(
                "Generating graph for period: {} ({} seconds)".format(
                    period, str(duration)
                )
            )

            graph_file = "{}_graph.png".format(period)

            # generate the graph
            rrdtool.graph(
                "/tmp/" + graph_file,
                "--start",
                "-%i" % duration,
                "--end",
                "-1",
                "--width",
                "800",
                "--height",
                "600",
                "--full-size-mode",
                "--slope-mode",
                "--units-exponent",
                "0",  # Set Y axis units to base scale (no K, M, etc.)
                "--imgformat",
                "PNG",
                "--watermark=cloudguyinbroadstone.com",
                "--title",
                "Gumtree items for sale in the last "
                + period
                + ", 1 mile from Broadstone",
                f"DEF:salecount=/tmp/{rrd_file}:sale-count:AVERAGE",
                "LINE2:salecount#FF0000:Sale Count\\n",
                "GPRINT:salecount:MIN: Min%6.0lf\\n",
                "GPRINT:salecount:MAX: Max%6.0lf\\n",
                "GPRINT:salecount:AVERAGE: Average%6.0lf",
            )

            print("Generated {} graph: /tmp/{}".format(period, graph_file))

        # upload the data files back to S3
        move_files(
            "upload",
            [
                rrd_file,
                csv_file,
                "hour_graph.png",
                "day_graph.png",
                "week_graph.png",
                "month_graph.png",
                "year_graph.png",
            ],
        )

        # invalidate CloudFront cache if refresh_distribution is "true"
        if refresh_distribution.lower() == "true":
            print(
                "Invalidating CloudFront cache because refresh_distribution = |{}|".format(
                    refresh_distribution
                )
            )
            cloudfront = boto3.client("cloudfront")
            result = cloudfront.create_invalidation(
                DistributionId=distribution,
                InvalidationBatch={
                    "Paths": {
                        "Quantity": 5,
                        "Items": [
                            "/images/year_graph.png",
                            "/images/hour_graph.png",
                            "/images/day_graph.png",
                            "/images/month_graph.png",
                            "/images/week_graph.png",
                        ],
                    },
                    "CallerReference": str(time.time()).replace(".", ""),
                },
            )
            invalidation_id = result["Invalidation"]["Id"]
            message = (
                f"Invalidated CloudFront cache. Invalidation ID: {invalidation_id}"
            )

        elif refresh_distribution.lower() == "false":
            message = "Skipping CloudFront cache invalidation. Repo variable REFRESH_DISTRIBUTION = |{}|".format(
                refresh_distribution
            )

        # log cache invalidation message
        print(message)

        # return successful lambda response
        return {
            "statusCode": 200,
            "body": "Successfully updated RRD file, generated graphs. " + message,
        }
    else:
        item_count = 0
        # return unsuccessful lambda response
        return {
            "statusCode": 500,
            "body": "Failed to update RRD file.  H1 value was not found in |"
            + url
            + "|",
        }


def main():
    handler(None, None)


if __name__ == "__main__":
    main()
