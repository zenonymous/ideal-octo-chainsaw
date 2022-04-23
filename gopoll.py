#!/usr/bin/python3

import datetime
import json
import pymysql.cursors
import requests

db = pymysql.connect(host='localhost',
                    user='user',
                    password='password',
                    db='db')

x = requests.get('https://greenmo.core.gourban-mobility.com/front/vehicles?lat=52.364431&lng=5.222011&rad=500').json()

for item in x:
    #gps is not accurate, compare last record with current data before inserting a new one
    with db.cursor() as cursor:
        sql = "SELECT `lng`, `lat`, `remainingKilometers` FROM `go` WHERE `licensePlate`=%s ORDER BY date DESC LIMIT 1"
        cursor.execute(sql, (item['licensePlate']))
        result = cursor.fetchone()
        if 'remainingKilometers' in item:
          if result is not None:
            change_lng = ((float(result[0])-item['position']['coordinates'][0])/item['position']['coordinates'][0])*100
            change_lat = ((float(result[1])-item['position']['coordinates'][1])/item['position']['coordinates'][1])*100
            if change_lng != 0 or change_lat != 0 :
              if ( result[2] != item['remainingKilometers'] ):
                with db.cursor() as cursor:
                   sql = "INSERT IGNORE INTO `go` (`id`, `licensePlate`, `stateOfCharge`, `lat`, `lng`, `remainingKilometers`) VALUES (%s, %s, %s, %s, %s, %s)"
                   cursor.execute(
                   sql, (item['id'], item['licensePlate'], item['stateOfCharge'], item['position']['coordinates'][1], item['position']['coordinates'][0], item['remainingKilometers']))
db.commit()
