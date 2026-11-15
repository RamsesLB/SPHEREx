from django import forms
from django.utils.translation import gettext_lazy as _

from . import services


class CoordinateForm(forms.Form):
    ra = forms.CharField(
        label=_("Right ascension"),
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "id": "ra",
            "placeholder": "08h55m10.831s",
            "autocomplete": "off",
            "readonly": True,
        }),
    )
    dec = forms.CharField(
        label=_("Declination"),
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "id": "dec",
            "placeholder": "-7d14m42.53s",
            "autocomplete": "off",
            "readonly": True,
        }),
    )
    collection = forms.ChoiceField(
        label=_("Collection"),
        required=False,
        choices=(),
        help_text=_("Only this SPHEREx release is searched. New releases appear in this list."),
        widget=forms.Select(attrs={"class": "form-select", "id": "collection"}),
    )
    advanced = forms.BooleanField(
        label=_("Advanced search"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "advanced-search"}),
    )
    collections = forms.MultipleChoiceField(
        label=_("Releases"),
        required=False,
        choices=(),
    )
    detector = forms.ChoiceField(
        label=_("Detector"),
        required=False,
        choices=[(str(number), str(number)) for number in range(1, 7)],
        initial="2",
        widget=forms.Select(attrs={"class": "form-select", "id": "detector"}),
    )
    fov = forms.FloatField(
        label=_("Side"),
        required=True,
        initial=60,
        min_value=0.1,
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "id": "fov",
            "step": "0.1",
            "min": "0.1",
        }),
    )
    unit = forms.ChoiceField(
        label=_("Unit"),
        choices=(
            ("arcsec", _("Arcseconds")),
            ("arcmin", _("Arcminutes")),
            ("deg", _("Degrees")),
        ),
        required=True,
        initial="arcsec",
        widget=forms.Select(attrs={"class": "form-select", "id": "unit"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = services.collection_choices()
        posted = self.data.get("collection") if self.is_bound else None
        names = [name for name, _label in choices]
        if posted and posted not in names:
            choices = [*choices, (posted, posted)]
            names.append(posted)
        self.fields["collection"].choices = choices
        self.fields["collections"].choices = choices
        if not self.is_bound:
            self.fields["collection"].initial = services.default_collection(names)
        self.fields["detector"].choices = [
            (str(number), _("Detector %(number)s") % {"number": number})
            for number in range(1, 7)
        ]

    def clean_ra(self):
        return services.normalize_angle(self.cleaned_data.get("ra", ""))

    def clean_dec(self):
        return services.normalize_angle(self.cleaned_data.get("dec", ""))

    def clean_detector(self):
        value = self.cleaned_data.get("detector") or "2"
        if value not in {"1", "2", "3", "4", "5", "6"}:
            return "2"
        return value

    def clean_collection(self):
        value = self.cleaned_data.get("collection")
        names = [name for name, _label in self.fields["collection"].choices]
        if value in names:
            return value
        return services.default_collection(names)

    def clean(self):
        cleaned = super().clean()
        ra = cleaned.get("ra")
        dec = cleaned.get("dec")
        if ra and dec:
            try:
                services.parse_coordinates(ra, dec)
            except services.SearchError as exc:
                raise forms.ValidationError(str(exc)) from exc
        fov = cleaned.get("fov")
        unit = cleaned.get("unit")
        if fov is not None and unit:
            try:
                services.fov_to_arcsec(fov, unit)
            except services.SearchError as exc:
                self.add_error("fov", str(exc))
        names = [name for name, _label in self.fields["collections"].choices]
        picked = [name for name in (cleaned.get("collections") or []) if name in names]
        single = cleaned.get("collection")
        if cleaned.get("advanced"):
            if not picked:
                self.add_error("collections", _("Select at least one release."))
            cleaned["collections"] = picked or ([single] if single else [])
        else:
            cleaned["collections"] = [single] if single else []
        return cleaned
