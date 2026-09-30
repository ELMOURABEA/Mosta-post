from django.db import migrations


def delete_impact_measurement_plans(apps, schema_editor):
    artefact = apps.get_model("signals", "SignalReportArtefact")
    artefact.objects.using(schema_editor.connection.alias).filter(type="impact_measurement_plan").delete()


class Migration(migrations.Migration):
    dependencies = [("signals", "0159_add_report_check_approval")]

    operations = [migrations.RunPython(delete_impact_measurement_plans, migrations.RunPython.noop)]
