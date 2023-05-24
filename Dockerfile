FROM --platform=linux/amd64 python:3.12-rc-alpine

COPY . /tool

WORKDIR /tool/python

RUN pip install -r requirements.txt

EXPOSE 8080

ENTRYPOINT [ "python", "main.py", "--address", ":8080" ]
