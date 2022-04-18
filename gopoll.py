#!/usr/bin/python3

import datetime
import json
import pymysql.cursors
import requests

db = pymysql.connect(host='localhost',
                    user='user',
                    password='password',
                    db='db')

x = requests.get('https://greenmo.core.gourban-mobility.com/front/vehicles?lat=52.364431&lng=5.222011&rad=5').json()

for item in x:
    #turns out remainingKilometers isnt always there
    if 'remainingKilometers' in item:
    	print(item['remainingKilometers'])
    else:
        item['remainingKilometers'] = 0;
    with db.cursor() as cursor:
        sql = "INSERT IGNORE INTO `go` (`id`, `licensePlate`, `stateOfCharge`, `lat`, `lng`, `remainingKilometers`) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(
        sql, (item['id'], item['licensePlate'], item['stateOfCharge'], item['position']['coordinates'][1], item['position']['coordinates'][0], item['remainingKilometers']))
db.commit()
