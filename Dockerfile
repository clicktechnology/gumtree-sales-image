FROM public.ecr.aws/lambda/python:3.11

# Install additional packages if necessary
RUN yum update -y && \
    yum install -y rrdtool \
    gcc \
    rrdtool-devel \
    rrdtool-python \
    librrd-devel \
    python-devel && \
    yum clean all && \
    rm -rf /var/cache/yum

# Copy requirements.txt
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install the specified packages
RUN pip3 install --upgrade pip && \
    pip3 install -r requirements.txt

# Copy function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "lambda_function.handler" ]
