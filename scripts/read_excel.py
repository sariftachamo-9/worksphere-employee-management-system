import pandas as pd

def find_ngawang(filename):
    try:
        df = pd.read_excel(f'database/{filename}')
        matches = df[df.apply(lambda row: row.astype(str).str.contains('Ngawang', case=False).any(), axis=1)]
        if not matches.empty:
            print(f"Found in {filename}:")
            print(matches.to_dict('records'))
    except Exception as e:
        pass

for f in ['employee.xlsx', 'intern.xlsx', 'student.xlsx']:
    find_ngawang(f)
