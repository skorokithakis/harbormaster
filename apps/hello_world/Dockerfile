FROM python:3.11-alpine

ENV PYTHONUNBUFFERED=1

RUN pip install Flask==2.3.2

RUN mkdir /code
WORKDIR /code

COPY app.py /code/

CMD "flask run -h 0.0.0.0 -p 8000"
